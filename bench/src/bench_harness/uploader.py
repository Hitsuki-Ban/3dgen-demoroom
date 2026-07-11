from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from bench_harness.meta import validate_failed_task_output, validate_task_output


REQUIRED_R2_ENV_VARS = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
PUBLISH_SHA256_METADATA_KEY = "sha256"
PUBLISH_LOCK_METADATA_KEY = "publish-id"
PUBLISH_LOCK_STATE_METADATA_KEY = "publish-state"
PUBLISH_LOCK_STATE_OWNED = "owned"
PUBLISH_LOCK_STATE_RELEASED = "released"
DELETE_BATCH_SIZE = 1000
MIN_RETRY_GLB_SIZE_RATIO = 0.1
TASK_MARKER_NAMES = frozenset({"meta.json", "failure.json"})


class PublishRecoveryRequiredError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        primary_error: BaseException | None = None,
        lock_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.lock_error = lock_error


def validate_relative_upload_name(relative_name: str) -> Path:
    relative_path = Path(relative_name)
    if relative_path == Path("."):
        return Path("")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(
            "upload target must be a relative path under the uploader root"
        )
    return relative_path


@dataclass(frozen=True)
class LocalUploader:
    root: Path

    def upload_run(self, source_dir: Path, relative_name: str) -> Path:
        if not source_dir.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {source_dir}")
        relative_path = validate_relative_upload_name(relative_name)

        destination = self.root / relative_path
        if destination.exists():
            raise FileExistsError(f"upload destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, destination)
        return destination


@dataclass(frozen=True)
class S3UploadConfig:
    bucket: str
    prefix: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_target(cls, target: str, env: Mapping[str, str]) -> S3UploadConfig:
        parsed = urlparse(target)
        if parsed.scheme != "s3" or not parsed.netloc:
            raise ValueError("S3 upload target must use s3://<bucket>/<prefix>")
        missing = [name for name in REQUIRED_R2_ENV_VARS if not env.get(name)]
        if missing:
            raise ValueError(
                f"missing required R2 environment variable(s): {', '.join(missing)}"
            )
        return cls(
            bucket=parsed.netloc,
            prefix=parsed.path.strip("/"),
            endpoint_url=env["R2_ENDPOINT"],
            access_key_id=env["R2_ACCESS_KEY_ID"],
            secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        )


@dataclass(frozen=True)
class LocalObject:
    relative_key: str
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class RemoteObject:
    key: str
    size: int
    etag: str
    sha256_metadata: str | None


@dataclass(frozen=True)
class PublishLock:
    publish_id: str
    state: str
    etag: str


@dataclass(frozen=True)
class S3Uploader:
    config: S3UploadConfig
    client: Any | None = None

    def upload_run(self, source_dir: Path, relative_name: str = "") -> list[str]:
        if not source_dir.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {source_dir}")
        relative_path = validate_relative_upload_name(relative_name)
        client = (
            self.client if self.client is not None else create_s3_client(self.config)
        )
        if not relative_path.parts:
            return self._upload_direct(client, source_dir)

        marker_name = self._validate_task_source(source_dir, relative_path)
        local_objects = self._collect_local_objects(source_dir)
        canonical_prefix = self._key(relative_path.as_posix()) + "/"
        publish_id = uuid.uuid4().hex
        lock_key = self._key(".publish-locks", f"{relative_path.as_posix()}.json")
        lock_etag = self._acquire_publish_lock(client, lock_key, publish_id)

        active_error: BaseException | None = None
        release_lock = True
        try:
            return self._publish_locked(
                client,
                local_objects,
                canonical_prefix=canonical_prefix,
                marker_name=marker_name,
                publish_id=publish_id,
                lock_key=lock_key,
            )
        except PublishRecoveryRequiredError as error:
            active_error = error
            release_lock = False
            raise
        except BaseException as error:
            active_error = error
            raise
        finally:
            if release_lock:
                try:
                    self._release_publish_lock(
                        client,
                        lock_key,
                        publish_id,
                        owned_etag=lock_etag,
                    )
                except Exception as lock_error:
                    if active_error is not None:
                        raise PublishRecoveryRequiredError(
                            "task publish failed and lock release also failed or is "
                            f"uncertain; inspect {lock_key} for publish-id {publish_id}; "
                            "manual recovery is required before retrying; primary error: "
                            f"{type(active_error).__name__}: {active_error}",
                            primary_error=active_error,
                            lock_error=lock_error,
                        ) from lock_error
                    raise PublishRecoveryRequiredError(
                        "task publish completed but lock release failed or is uncertain; "
                        f"inspect {lock_key} for publish-id {publish_id} before retrying",
                        lock_error=lock_error,
                    ) from lock_error

    def _publish_locked(
        self,
        client: Any,
        local_objects: list[LocalObject],
        *,
        canonical_prefix: str,
        marker_name: str,
        publish_id: str,
        lock_key: str,
    ) -> list[str]:
        old_objects = self._list_remote_objects(client, canonical_prefix)
        self._validate_retry_glb_size(local_objects, old_objects, canonical_prefix)
        staging_prefix = self._key(".publish-staging", publish_id) + "/"
        backup_prefix = self._key(".publish-backup", publish_id) + "/"
        try:
            staged_objects = self._upload_staging(client, local_objects, staging_prefix)
        except Exception as exc:
            raise RuntimeError(
                "staging upload or validation failed; canonical is unchanged; "
                f"staging retained at {staging_prefix}"
            ) from exc

        try:
            backup_objects = self._backup_canonical(
                client,
                old_objects,
                canonical_prefix=canonical_prefix,
                backup_prefix=backup_prefix,
            )
        except Exception as exc:
            raise RuntimeError(
                "publish backup failed before canonical mutation; "
                f"staging is {staging_prefix}; partial backup may remain at {backup_prefix}"
            ) from exc

        try:
            self._commit_staging(
                client,
                staged_objects,
                old_objects,
                canonical_prefix=canonical_prefix,
                marker_name=marker_name,
            )
        except BaseException as exc:
            try:
                self._restore_canonical(
                    client,
                    backup_objects,
                    canonical_prefix=canonical_prefix,
                    backup_prefix=backup_prefix,
                )
            except BaseException as rollback_exc:
                raise PublishRecoveryRequiredError(
                    "publish failed and rollback failed; "
                    f"manual recovery source is {backup_prefix}; staging is {staging_prefix}; "
                    f"task lock retained at {lock_key}"
                ) from rollback_exc
            if not isinstance(exc, Exception):
                raise
            raise RuntimeError(
                f"publish failed; previous canonical restored; staging retained at {staging_prefix}"
            ) from exc

        try:
            self._delete_prefix(client, staging_prefix)
            self._delete_prefix(client, backup_prefix)
        except Exception as exc:
            raise RuntimeError(
                "canonical publish committed but cleanup failed; "
                f"remove staging {staging_prefix} and backup {backup_prefix} manually"
            ) from exc

        return [canonical_prefix + item.relative_key for item in local_objects]

    def _acquire_publish_lock(self, client: Any, lock_key: str, publish_id: str) -> str:
        try:
            self._write_publish_lock(
                client,
                lock_key,
                publish_id=publish_id,
                state=PUBLISH_LOCK_STATE_OWNED,
                if_none_match="*",
            )
        except Exception as create_error:
            return self._acquire_existing_publish_lock(
                client,
                lock_key,
                publish_id=publish_id,
                create_error=create_error,
            )
        return self._confirm_publish_lock_owner(client, lock_key, publish_id)

    def _acquire_existing_publish_lock(
        self,
        client: Any,
        lock_key: str,
        *,
        publish_id: str,
        create_error: Exception,
    ) -> str:
        try:
            current = self._read_publish_lock(client, lock_key)
        except Exception as inspect_error:
            raise PublishRecoveryRequiredError(
                "task publish lock acquisition failed and its outcome is uncertain; "
                f"inspect {lock_key} before retrying publish-id {publish_id}",
                lock_error=create_error,
            ) from inspect_error

        if current.state == PUBLISH_LOCK_STATE_OWNED:
            if current.publish_id == publish_id:
                return current.etag
            raise RuntimeError(
                "task publish lock is already owned by another transaction: "
                f"{lock_key} publish-id={current.publish_id}"
            ) from create_error

        try:
            self._write_publish_lock(
                client,
                lock_key,
                publish_id=publish_id,
                state=PUBLISH_LOCK_STATE_OWNED,
                if_match=current.etag,
            )
        except Exception as compare_error:
            try:
                observed = self._read_publish_lock(client, lock_key)
            except Exception as inspect_error:
                raise PublishRecoveryRequiredError(
                    "task publish lock compare-and-swap failed and its outcome is "
                    f"uncertain; inspect {lock_key} before retrying publish-id {publish_id}",
                    lock_error=compare_error,
                ) from inspect_error
            if (
                observed.state == PUBLISH_LOCK_STATE_OWNED
                and observed.publish_id == publish_id
            ):
                return observed.etag
            if observed.state == PUBLISH_LOCK_STATE_OWNED:
                raise RuntimeError(
                    "task publish lock was acquired concurrently by another transaction: "
                    f"{lock_key} publish-id={observed.publish_id}"
                ) from compare_error
            raise RuntimeError(
                "task publish lock compare-and-swap did not acquire the released lock: "
                f"{lock_key}; retry with a new publish transaction"
            ) from compare_error

        return self._confirm_publish_lock_owner(client, lock_key, publish_id)

    def _release_publish_lock(
        self,
        client: Any,
        lock_key: str,
        publish_id: str,
        *,
        owned_etag: str,
    ) -> None:
        try:
            self._write_publish_lock(
                client,
                lock_key,
                publish_id=publish_id,
                state=PUBLISH_LOCK_STATE_RELEASED,
                if_match=owned_etag,
            )
        except BaseException as release_error:
            try:
                current = self._read_publish_lock(client, lock_key)
            except BaseException as inspect_error:
                raise PublishRecoveryRequiredError(
                    "task publish lock release failed and its outcome is uncertain; "
                    f"inspect {lock_key} for publish-id {publish_id}",
                    lock_error=release_error,
                ) from inspect_error

            release_was_applied = (
                current.state == PUBLISH_LOCK_STATE_RELEASED
                or current.publish_id != publish_id
            )
            if release_was_applied:
                if not isinstance(release_error, Exception):
                    raise
                return
            raise PublishRecoveryRequiredError(
                "task publish lock remains owned after release failed; "
                f"manual recovery is required at {lock_key} for publish-id {publish_id}",
                lock_error=release_error,
            ) from release_error

    def _write_publish_lock(
        self,
        client: Any,
        lock_key: str,
        *,
        publish_id: str,
        state: str,
        if_none_match: str | None = None,
        if_match: str | None = None,
    ) -> None:
        if (if_none_match is None) == (if_match is None):
            raise ValueError("publish lock write requires exactly one ETag condition")
        if state not in {PUBLISH_LOCK_STATE_OWNED, PUBLISH_LOCK_STATE_RELEASED}:
            raise ValueError(f"invalid publish lock state: {state}")
        body = (
            json.dumps(
                {
                    "publish_id": publish_id,
                    "state": state,
                    "transition_id": uuid.uuid4().hex,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        request: dict[str, Any] = {
            "Bucket": self.config.bucket,
            "Key": lock_key,
            "Body": body,
            "ContentType": "application/json",
            "Metadata": {
                PUBLISH_LOCK_METADATA_KEY: publish_id,
                PUBLISH_LOCK_STATE_METADATA_KEY: state,
            },
        }
        if if_none_match is not None:
            request["IfNoneMatch"] = if_none_match
        else:
            request["IfMatch"] = if_match
        client.put_object(**request)

    def _confirm_publish_lock_owner(
        self, client: Any, lock_key: str, publish_id: str
    ) -> str:
        try:
            current = self._read_publish_lock(client, lock_key)
        except Exception as inspect_error:
            raise PublishRecoveryRequiredError(
                "task publish lock write succeeded but ownership verification failed; "
                f"inspect {lock_key} before retrying publish-id {publish_id}",
                lock_error=inspect_error,
            ) from inspect_error
        if (
            current.state != PUBLISH_LOCK_STATE_OWNED
            or current.publish_id != publish_id
        ):
            raise PublishRecoveryRequiredError(
                "task publish lock ownership mismatch after conditional write; "
                f"inspect {lock_key}; expected owned publish-id {publish_id}, "
                f"received {current.state} publish-id {current.publish_id}"
            )
        return current.etag

    def _read_publish_lock(self, client: Any, lock_key: str) -> PublishLock:
        head = client.head_object(Bucket=self.config.bucket, Key=lock_key)
        metadata = head.get("Metadata") or {}
        publish_id = metadata.get(PUBLISH_LOCK_METADATA_KEY)
        state = metadata.get(PUBLISH_LOCK_STATE_METADATA_KEY)
        etag = head.get("ETag")
        if not isinstance(publish_id, str) or not publish_id:
            raise RuntimeError(f"publish lock has no publish-id metadata: {lock_key}")
        if state not in {PUBLISH_LOCK_STATE_OWNED, PUBLISH_LOCK_STATE_RELEASED}:
            raise RuntimeError(f"publish lock has invalid state at {lock_key}: {state}")
        if not isinstance(etag, str) or not etag:
            raise RuntimeError(f"publish lock has no ETag: {lock_key}")
        return PublishLock(publish_id=publish_id, state=state, etag=etag)

    def _upload_direct(self, client: Any, source_dir: Path) -> list[str]:
        source_files = sorted(path for path in source_dir.rglob("*") if path.is_file())
        nested_files = [
            path.relative_to(source_dir).as_posix()
            for path in source_files
            if len(path.relative_to(source_dir).parts) != 1
        ]
        if nested_files:
            raise ValueError(
                "direct S3 upload accepts top-level telemetry files only; "
                f"nested files require an explicit publish protocol: {nested_files}"
            )
        task_artifacts = sorted(
            path.name
            for path in source_files
            if path.name in TASK_MARKER_NAMES or path.name == "output.glb"
        )
        if task_artifacts:
            raise ValueError(
                "task artifacts require an explicit relative task ID; "
                f"direct upload rejected: {task_artifacts}"
            )

        uploaded_keys: list[str] = []
        for source_file in source_files:
            key = self._key(source_file.relative_to(source_dir).as_posix())
            client.upload_file(str(source_file), self.config.bucket, key)
            uploaded_keys.append(key)
        return uploaded_keys

    def _validate_task_source(self, source_dir: Path, relative_path: Path) -> str:
        if len(relative_path.parts) != 1:
            raise ValueError("task publish target must be exactly one task ID")
        target_parts = tuple(part for part in self.config.prefix.split("/") if part)
        if len(target_parts) < 2 or target_parts[0] != "runs":
            raise ValueError("task publish S3 prefix must match runs/<model-id>/...")

        meta_path = source_dir / "meta.json"
        glb_path = source_dir / "output.glb"
        failure_path = source_dir / "failure.json"
        has_success = meta_path.is_file() or glb_path.is_file()
        has_failure = failure_path.is_file()
        if has_failure and has_success:
            raise ValueError("task upload must be exclusively success or failed")
        if has_failure:
            payload = validate_failed_task_output(source_dir)
            marker_name = "failure.json"
        else:
            payload = validate_task_output(source_dir)
            marker_name = "meta.json"

        expected_task_id = relative_path.name
        if payload["task_id"] != expected_task_id:
            raise ValueError(
                f"task upload ID mismatch: target {expected_task_id}, payload {payload['task_id']}"
            )
        expected_model_id = target_parts[1]
        if payload["model_id"] != expected_model_id:
            raise ValueError(
                "model upload ID mismatch: "
                f"target {expected_model_id}, payload {payload['model_id']}"
            )
        return marker_name

    def _collect_local_objects(self, source_dir: Path) -> list[LocalObject]:
        objects = []
        for source_file in sorted(
            path for path in source_dir.rglob("*") if path.is_file()
        ):
            objects.append(
                LocalObject(
                    relative_key=source_file.relative_to(source_dir).as_posix(),
                    path=source_file,
                    size=source_file.stat().st_size,
                    sha256=_sha256_file(source_file),
                )
            )
        if not objects:
            raise ValueError(f"task upload contains no files: {source_dir}")
        return objects

    def _upload_staging(
        self,
        client: Any,
        local_objects: list[LocalObject],
        staging_prefix: str,
    ) -> dict[str, RemoteObject]:
        staged: dict[str, RemoteObject] = {}
        for item in local_objects:
            key = staging_prefix + item.relative_key
            client.upload_file(
                str(item.path),
                self.config.bucket,
                key,
                ExtraArgs={"Metadata": {PUBLISH_SHA256_METADATA_KEY: item.sha256}},
            )
            staged[item.relative_key] = self._head_verified(
                client,
                key,
                expected_size=item.size,
                expected_sha256_metadata=item.sha256,
            )
        return staged

    def _backup_canonical(
        self,
        client: Any,
        old_objects: dict[str, RemoteObject],
        *,
        canonical_prefix: str,
        backup_prefix: str,
    ) -> dict[str, RemoteObject]:
        backup: dict[str, RemoteObject] = {}
        for key, item in sorted(old_objects.items()):
            relative_key = key.removeprefix(canonical_prefix)
            backup[relative_key] = self._copy_verified(
                client, item, backup_prefix + relative_key
            )
        return backup

    def _commit_staging(
        self,
        client: Any,
        staged_objects: dict[str, RemoteObject],
        old_objects: dict[str, RemoteObject],
        *,
        canonical_prefix: str,
        marker_name: str,
    ) -> None:
        marker_keys = [canonical_prefix + name for name in sorted(TASK_MARKER_NAMES)]
        self._delete_keys(client, [key for key in marker_keys if key in old_objects])

        for relative_key, item in sorted(staged_objects.items()):
            if relative_key != marker_name:
                self._copy_verified(client, item, canonical_prefix + relative_key)

        new_keys = {canonical_prefix + relative_key for relative_key in staged_objects}
        stale_keys = sorted(set(old_objects) - new_keys - set(marker_keys))
        self._delete_keys(client, stale_keys)
        self._copy_verified(
            client, staged_objects[marker_name], canonical_prefix + marker_name
        )

    def _restore_canonical(
        self,
        client: Any,
        backup_objects: dict[str, RemoteObject],
        *,
        canonical_prefix: str,
        backup_prefix: str,
    ) -> None:
        self._delete_prefix(client, canonical_prefix)
        ordered = sorted(
            backup_objects.items(),
            key=lambda item: (item[0] in TASK_MARKER_NAMES, item[0]),
        )
        for relative_key, item in ordered:
            self._copy_verified(client, item, canonical_prefix + relative_key)
        restored_keys = set(self._list_remote_objects(client, canonical_prefix))
        expected_keys = {
            canonical_prefix + relative_key for relative_key in backup_objects
        }
        if restored_keys != expected_keys:
            raise RuntimeError(
                f"canonical rollback key mismatch from {backup_prefix}: "
                f"expected {sorted(expected_keys)}, received {sorted(restored_keys)}"
            )

    def _copy_verified(
        self, client: Any, source: RemoteObject, destination_key: str
    ) -> RemoteObject:
        client.copy_object(
            Bucket=self.config.bucket,
            Key=destination_key,
            CopySource={"Bucket": self.config.bucket, "Key": source.key},
            CopySourceIfMatch=source.etag,
        )
        return self._head_verified(
            client,
            destination_key,
            expected_size=source.size,
            expected_sha256_metadata=source.sha256_metadata,
        )

    def _head_verified(
        self,
        client: Any,
        key: str,
        *,
        expected_size: int,
        expected_sha256_metadata: str | None,
    ) -> RemoteObject:
        response = client.head_object(Bucket=self.config.bucket, Key=key)
        size = response.get("ContentLength")
        if size != expected_size:
            raise RuntimeError(
                f"remote size mismatch for {key}: expected {expected_size}, received {size}"
            )
        metadata = response.get("Metadata") or {}
        sha256_metadata = metadata.get(PUBLISH_SHA256_METADATA_KEY)
        if (
            expected_sha256_metadata is not None
            and sha256_metadata != expected_sha256_metadata
        ):
            raise RuntimeError(
                "remote SHA-256 metadata mismatch for "
                f"{key}: expected {expected_sha256_metadata}, received {sha256_metadata}"
            )
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise RuntimeError(f"remote object has no ETag: {key}")
        return RemoteObject(
            key=key,
            size=expected_size,
            etag=etag,
            sha256_metadata=sha256_metadata,
        )

    def _list_remote_objects(self, client: Any, prefix: str) -> dict[str, RemoteObject]:
        objects: dict[str, RemoteObject] = {}
        for key in self._list_keys(client, prefix):
            head = client.head_object(Bucket=self.config.bucket, Key=key)
            size = head.get("ContentLength")
            etag = head.get("ETag")
            if not isinstance(size, int) or size < 0:
                raise RuntimeError(f"remote object has invalid size: {key}")
            if not isinstance(etag, str) or not etag:
                raise RuntimeError(f"remote object has no ETag: {key}")
            metadata = head.get("Metadata") or {}
            objects[key] = RemoteObject(
                key=key,
                size=size,
                etag=etag,
                sha256_metadata=metadata.get(PUBLISH_SHA256_METADATA_KEY),
            )
        return objects

    def _validate_retry_glb_size(
        self,
        local_objects: list[LocalObject],
        old_objects: dict[str, RemoteObject],
        canonical_prefix: str,
    ) -> None:
        new_glb = next(
            (item for item in local_objects if item.relative_key == "output.glb"), None
        )
        old_glb = old_objects.get(canonical_prefix + "output.glb")
        if new_glb is None or old_glb is None:
            return
        if new_glb.size < old_glb.size * MIN_RETRY_GLB_SIZE_RATIO:
            raise ValueError(
                "retry output.glb is less than 10% of the previous canonical size: "
                f"new={new_glb.size} old={old_glb.size}"
            )

    def _key(self, *parts: str) -> str:
        return "/".join(
            part.strip("/") for part in (self.config.prefix, *parts) if part.strip("/")
        )

    def _list_keys(self, client: Any, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            request: dict[str, Any] = {"Bucket": self.config.bucket, "Prefix": prefix}
            if continuation_token is not None:
                request["ContinuationToken"] = continuation_token
            response = client.list_objects_v2(**request)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                return sorted(keys)
            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                raise RuntimeError(
                    "S3 listing was truncated without a continuation token"
                )

    def _delete_keys(self, client: Any, keys: list[str]) -> None:
        for start in range(0, len(keys), DELETE_BATCH_SIZE):
            batch = keys[start : start + DELETE_BATCH_SIZE]
            if not batch:
                continue
            response = client.delete_objects(
                Bucket=self.config.bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            if isinstance(response, dict) and response.get("Errors"):
                raise RuntimeError(f"S3 delete failed: {response['Errors']}")

    def _delete_prefix(self, client: Any, prefix: str) -> None:
        self._delete_keys(client, self._list_keys(client, prefix))
        remaining = self._list_keys(client, prefix)
        if remaining:
            raise RuntimeError(
                f"S3 prefix cleanup incomplete for {prefix}: {remaining}"
            )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_s3_client(config: S3UploadConfig) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for S3/R2 uploads") from exc
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
    )


def create_uploader(
    kind: str,
    target: str,
    *,
    env: Mapping[str, str] | None = None,
    s3_client: Any | None = None,
) -> LocalUploader | S3Uploader:
    if kind == "local":
        return LocalUploader(Path(target))
    if kind == "s3":
        return S3Uploader(
            S3UploadConfig.from_target(target, os.environ if env is None else env),
            client=s3_client,
        )
    raise ValueError(f"unknown uploader kind: {kind}")
