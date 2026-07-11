from __future__ import annotations

import hashlib
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
DELETE_BATCH_SIZE = 1000
MIN_RETRY_GLB_SIZE_RATIO = 0.1
TASK_MARKER_NAMES = frozenset({"meta.json", "failure.json"})


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
    sha256: str | None


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
        old_objects = self._list_remote_objects(client, canonical_prefix)
        self._validate_retry_glb_size(local_objects, old_objects, canonical_prefix)

        publish_id = uuid.uuid4().hex
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
                f"publish backup failed before canonical mutation; staging retained at {staging_prefix}"
            ) from exc

        try:
            self._commit_staging(
                client,
                staged_objects,
                old_objects,
                canonical_prefix=canonical_prefix,
                marker_name=marker_name,
            )
        except Exception as exc:
            try:
                self._restore_canonical(
                    client,
                    backup_objects,
                    canonical_prefix=canonical_prefix,
                    backup_prefix=backup_prefix,
                )
            except Exception as rollback_exc:
                raise RuntimeError(
                    "publish failed and rollback failed; "
                    f"manual recovery source is {backup_prefix}; staging is {staging_prefix}"
                ) from rollback_exc
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

    def _upload_direct(self, client: Any, source_dir: Path) -> list[str]:
        uploaded_keys: list[str] = []
        for source_file in sorted(
            path for path in source_dir.rglob("*") if path.is_file()
        ):
            key = self._key(source_file.relative_to(source_dir).as_posix())
            client.upload_file(str(source_file), self.config.bucket, key)
            uploaded_keys.append(key)
        return uploaded_keys

    def _validate_task_source(self, source_dir: Path, relative_path: Path) -> str:
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
        target_parts = {
            part
            for part in (*self.config.prefix.split("/"), *relative_path.parts[:-1])
            if part
        }
        if payload["model_id"] not in target_parts:
            raise ValueError(
                f"model upload ID mismatch: target prefix {self.config.prefix}, payload {payload['model_id']}"
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
                expected_sha256=item.sha256,
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
            expected_sha256=source.sha256,
        )

    def _head_verified(
        self,
        client: Any,
        key: str,
        *,
        expected_size: int,
        expected_sha256: str | None,
    ) -> RemoteObject:
        response = client.head_object(Bucket=self.config.bucket, Key=key)
        size = response.get("ContentLength")
        if size != expected_size:
            raise RuntimeError(
                f"remote size mismatch for {key}: expected {expected_size}, received {size}"
            )
        metadata = response.get("Metadata") or {}
        sha256 = metadata.get(PUBLISH_SHA256_METADATA_KEY)
        if expected_sha256 is not None and sha256 != expected_sha256:
            raise RuntimeError(
                f"remote SHA-256 mismatch for {key}: expected {expected_sha256}, received {sha256}"
            )
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise RuntimeError(f"remote object has no ETag: {key}")
        return RemoteObject(key=key, size=expected_size, etag=etag, sha256=sha256)

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
                sha256=metadata.get(PUBLISH_SHA256_METADATA_KEY),
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
