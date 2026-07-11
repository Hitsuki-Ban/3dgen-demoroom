import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import pytest

from bench_harness.uploader import (
    LocalUploader,
    S3UploadConfig,
    S3Uploader,
    create_uploader,
)


MODEL_ID = "model-a"
TASK_ID = "task-a"
RUN_PREFIX = "runs/model-a/retry-run"
CANONICAL_PREFIX = f"{RUN_PREFIX}/{TASK_ID}/"


def _valid_meta(
    *, model_id: str = MODEL_ID, task_id: str = TASK_ID
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "model_id": model_id,
        "model_git_commit": "commit",
        "weights_revision": "revision",
        "gpu_name": "Test GPU",
        "wall_clock_seconds": 1.5,
        "peak_vram_bytes": 1024,
        "seed": 1,
        "parameters": {},
        "retry_count": 1,
        "torch_version": "2.7.1",
        "torch_cuda_version": "12.8",
        "torch_cuda_arch_list": ["sm_89"],
        "attention_backend": "sdpa",
        "started_at": "2026-07-08T00:00:00Z",
        "finished_at": "2026-07-08T00:00:02Z",
        "license_file": "LICENSE",
    }


def _write_success(
    source: Path,
    *,
    model_id: str = MODEL_ID,
    task_id: str = TASK_ID,
) -> None:
    source.mkdir()
    json_chunk = b'{"asset":{"version":"2.0"}}'
    json_chunk += b" " * (-len(json_chunk) % 4)
    total_size = 12 + 8 + len(json_chunk)
    (source / "output.glb").write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_size)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
    )
    (source / "LICENSE").write_text("license\n", encoding="utf-8")
    (source / "meta.json").write_text(
        json.dumps(_valid_meta(model_id=model_id, task_id=task_id)),
        encoding="utf-8",
    )


def _write_failure(source: Path) -> None:
    source.mkdir()
    failure = {
        "status": "failed",
        "task_id": TASK_ID,
        "model_id": MODEL_ID,
        "model_git_commit": "commit",
        "weights_revision": "revision",
        "seed": 1,
        "parameters": {},
        "retry_count": 1,
        "error_type": "RuntimeError",
        "error_message": "failed",
        "started_at": "2026-07-08T00:00:00Z",
        "finished_at": "2026-07-08T00:00:02Z",
    }
    (source / "failure.json").write_text(json.dumps(failure), encoding="utf-8")


@dataclass(frozen=True)
class FakeObject:
    body: bytes
    metadata: dict[str, str]

    @property
    def etag(self) -> str:
        return f'"{hashlib.md5(self.body, usedforsecurity=False).hexdigest()}"'


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, FakeObject] = {}
        self.operations: list[tuple[str, str, str | None]] = []
        self.upload_count = 0
        self.fail_upload_number: int | None = None
        self.strip_upload_metadata = False
        self.fail_copy_destination_once: str | None = None
        self.fail_delete_key_contains: str | None = None

    def put(
        self, key: str, body: bytes, metadata: dict[str, str] | None = None
    ) -> None:
        self.objects[key] = FakeObject(body=body, metadata=dict(metadata or {}))

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, object] | None = None,
    ) -> None:
        self.upload_count += 1
        if self.upload_count == self.fail_upload_number:
            raise OSError("injected upload failure")
        metadata = dict((ExtraArgs or {}).get("Metadata", {}))
        if self.strip_upload_metadata:
            metadata = {}
        self.put(key, Path(filename).read_bytes(), metadata)
        self.operations.append(("upload", key, None))

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        item = self.objects[Key]
        return {
            "ContentLength": len(item.body),
            "ETag": item.etag,
            "Metadata": dict(item.metadata),
        }

    def copy_object(
        self,
        *,
        Bucket: str,
        Key: str,
        CopySource: dict[str, str],
        CopySourceIfMatch: str,
    ) -> dict[str, object]:
        source_key = CopySource["Key"]
        source = self.objects[source_key]
        if source.etag != CopySourceIfMatch:
            raise RuntimeError("copy source ETag mismatch")
        if Key == self.fail_copy_destination_once:
            self.fail_copy_destination_once = None
            raise OSError("injected copy failure")
        self.objects[Key] = FakeObject(body=source.body, metadata=dict(source.metadata))
        self.operations.append(("copy", Key, source_key))
        return {"CopyObjectResult": {"ETag": source.etag}}

    def list_objects_v2(self, **request) -> dict[str, object]:
        prefix = request["Prefix"]
        return {
            "Contents": [
                {"Key": key} for key in sorted(self.objects) if key.startswith(prefix)
            ],
            "IsTruncated": False,
        }

    def delete_objects(
        self, *, Bucket: str, Delete: dict[str, object]
    ) -> dict[str, object]:
        keys = [item["Key"] for item in Delete["Objects"]]
        if self.fail_delete_key_contains and any(
            self.fail_delete_key_contains in key for key in keys
        ):
            raise OSError("injected cleanup failure")
        for key in keys:
            self.objects.pop(key, None)
            self.operations.append(("delete", key, None))
        return {}


def _config(prefix: str = RUN_PREFIX) -> S3UploadConfig:
    return S3UploadConfig(
        bucket="3dgen-runs",
        prefix=prefix,
        endpoint_url="https://example.r2.cloudflarestorage.com",
        access_key_id="access-key",
        secret_access_key="secret-key",
    )


def _canonical_bodies(client: FakeS3Client) -> dict[str, bytes]:
    return {
        key: item.body
        for key, item in client.objects.items()
        if key.startswith(CANONICAL_PREFIX)
    }


def test_local_uploader_copies_run_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "output.glb").write_bytes(b"glTF")
    target_root = tmp_path / "published"

    uploader = LocalUploader(target_root)
    uploaded = uploader.upload_run(source, "runs/triposr/local-test")

    assert uploaded == target_root / "runs" / "triposr" / "local-test"
    assert (uploaded / "output.glb").read_bytes() == b"glTF"


def test_local_uploader_rejects_parent_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    uploader = LocalUploader(tmp_path / "published")

    with pytest.raises(ValueError, match="relative"):
        uploader.upload_run(source, "../escape")


def test_s3_config_requires_s3_uri_and_explicit_credentials() -> None:
    env = {
        "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
        "R2_ACCESS_KEY_ID": "access-key",
        "R2_SECRET_ACCESS_KEY": "secret-key",
    }

    config = S3UploadConfig.from_target("s3://3dgen-runs/runs", env)

    assert config.bucket == "3dgen-runs"
    assert config.prefix == "runs"
    assert config.endpoint_url == "https://example.r2.cloudflarestorage.com"
    assert config.access_key_id == "access-key"
    assert config.secret_access_key == "secret-key"


def test_s3_config_fails_fast_when_required_env_is_missing() -> None:
    with pytest.raises(ValueError, match="R2_SECRET_ACCESS_KEY"):
        S3UploadConfig.from_target(
            "s3://3dgen-runs/runs",
            {
                "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
                "R2_ACCESS_KEY_ID": "access-key",
            },
        )


def test_s3_uploader_direct_mode_omits_dot_segment(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "probe.txt").write_text("probe\n", encoding="utf-8")
    client = FakeS3Client()
    uploader = S3Uploader(_config("_codex-s3-probe"), client=client)

    uploaded = uploader.upload_run(source)

    assert uploaded == ["_codex-s3-probe/probe.txt"]
    assert (
        client.objects["_codex-s3-probe/probe.txt"].body
        == (source / "probe.txt").read_bytes()
    )


def test_s3_uploader_replaces_success_via_staging_and_marker_last(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_success(source)
    client = FakeS3Client()
    client.put(CANONICAL_PREFIX + "LICENSE", b"old license")
    client.put(CANONICAL_PREFIX + "meta.json", b"old meta")
    client.put(CANONICAL_PREFIX + "output.glb", b"old glb")
    client.put(CANONICAL_PREFIX + "raw/old.bin", b"stale")
    client.put(f"{RUN_PREFIX}/other-task/meta.json", b"other")
    uploader = S3Uploader(_config(), client=client)

    uploaded = uploader.upload_run(source, TASK_ID)

    assert uploaded == [
        CANONICAL_PREFIX + "LICENSE",
        CANONICAL_PREFIX + "meta.json",
        CANONICAL_PREFIX + "output.glb",
    ]
    assert _canonical_bodies(client) == {
        CANONICAL_PREFIX + "LICENSE": (source / "LICENSE").read_bytes(),
        CANONICAL_PREFIX + "meta.json": (source / "meta.json").read_bytes(),
        CANONICAL_PREFIX + "output.glb": (source / "output.glb").read_bytes(),
    }
    assert client.objects[f"{RUN_PREFIX}/other-task/meta.json"].body == b"other"
    assert not any("/.publish-" in key for key in client.objects)
    canonical_copies = [
        key
        for operation, key, _ in client.operations
        if operation == "copy" and key.startswith(CANONICAL_PREFIX)
    ]
    assert canonical_copies[-1] == CANONICAL_PREFIX + "meta.json"


def test_s3_uploader_upload_failure_leaves_previous_canonical_untouched(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_success(source)
    client = FakeS3Client()
    client.put(CANONICAL_PREFIX + "failure.json", b"old failure")
    before = _canonical_bodies(client)
    client.fail_upload_number = 2
    uploader = S3Uploader(_config(), client=client)

    with pytest.raises(RuntimeError, match="staging retained"):
        uploader.upload_run(source, TASK_ID)

    assert _canonical_bodies(client) == before
    assert not any(
        operation in {"copy", "delete"} and key.startswith(CANONICAL_PREFIX)
        for operation, key, _ in client.operations
    )


def test_s3_uploader_replaces_success_with_failure_marker_last(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_failure(source)
    client = FakeS3Client()
    client.put(CANONICAL_PREFIX + "LICENSE", b"old license")
    client.put(CANONICAL_PREFIX + "meta.json", b"old meta")
    client.put(CANONICAL_PREFIX + "output.glb", b"old glb")
    uploader = S3Uploader(_config(), client=client)

    uploaded = uploader.upload_run(source, TASK_ID)

    assert uploaded == [CANONICAL_PREFIX + "failure.json"]
    assert _canonical_bodies(client) == {
        CANONICAL_PREFIX + "failure.json": (source / "failure.json").read_bytes()
    }
    canonical_copies = [
        key
        for operation, key, _ in client.operations
        if operation == "copy" and key.startswith(CANONICAL_PREFIX)
    ]
    assert canonical_copies[-1] == CANONICAL_PREFIX + "failure.json"


def test_s3_uploader_remote_validation_failure_leaves_canonical_untouched(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_success(source)
    client = FakeS3Client()
    client.put(CANONICAL_PREFIX + "failure.json", b"old failure")
    before = _canonical_bodies(client)
    client.strip_upload_metadata = True
    uploader = S3Uploader(_config(), client=client)

    with pytest.raises(RuntimeError, match="staging retained"):
        uploader.upload_run(source, TASK_ID)

    assert _canonical_bodies(client) == before


@pytest.mark.parametrize(
    ("model_id", "task_id", "message"),
    [
        ("wrong-model", TASK_ID, "model upload ID mismatch"),
        (MODEL_ID, "wrong-task", "task upload ID mismatch"),
    ],
)
def test_s3_uploader_rejects_payload_target_id_mismatch_before_upload(
    tmp_path: Path,
    model_id: str,
    task_id: str,
    message: str,
) -> None:
    source = tmp_path / "source"
    _write_success(source, model_id=model_id, task_id=task_id)
    client = FakeS3Client()
    uploader = S3Uploader(_config(), client=client)

    with pytest.raises(ValueError, match=message):
        uploader.upload_run(source, TASK_ID)

    assert client.operations == []


def test_s3_uploader_copy_failure_rolls_back_previous_canonical(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_success(source)
    client = FakeS3Client()
    client.put(CANONICAL_PREFIX + "failure.json", b"old failure")
    client.put(CANONICAL_PREFIX + "raw/evidence.txt", b"old evidence")
    before = _canonical_bodies(client)
    client.fail_copy_destination_once = CANONICAL_PREFIX + "output.glb"
    uploader = S3Uploader(_config(), client=client)

    with pytest.raises(RuntimeError, match="previous canonical restored"):
        uploader.upload_run(source, TASK_ID)

    assert _canonical_bodies(client) == before
    assert any("/.publish-staging/" in key for key in client.objects)
    assert any("/.publish-backup/" in key for key in client.objects)


def test_s3_uploader_cleanup_failure_preserves_committed_canonical(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_success(source)
    client = FakeS3Client()
    client.put(CANONICAL_PREFIX + "failure.json", b"old failure")
    client.fail_delete_key_contains = "/.publish-staging/"
    uploader = S3Uploader(_config(), client=client)

    with pytest.raises(
        RuntimeError, match="canonical publish committed but cleanup failed"
    ):
        uploader.upload_run(source, TASK_ID)

    assert _canonical_bodies(client) == {
        CANONICAL_PREFIX + "LICENSE": (source / "LICENSE").read_bytes(),
        CANONICAL_PREFIX + "meta.json": (source / "meta.json").read_bytes(),
        CANONICAL_PREFIX + "output.glb": (source / "output.glb").read_bytes(),
    }
    assert any("/.publish-staging/" in key for key in client.objects)
    assert any("/.publish-backup/" in key for key in client.objects)


def test_s3_uploader_rejects_extreme_retry_glb_shrink_before_staging(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_success(source)
    client = FakeS3Client()
    client.put(CANONICAL_PREFIX + "meta.json", b"old meta")
    client.put(CANONICAL_PREFIX + "output.glb", b"x" * 1000)
    before = _canonical_bodies(client)
    uploader = S3Uploader(_config(), client=client)

    with pytest.raises(ValueError, match="less than 10%"):
        uploader.upload_run(source, TASK_ID)

    assert _canonical_bodies(client) == before
    assert client.operations == []


def test_create_uploader_builds_s3_uploader_from_env() -> None:
    uploader = create_uploader(
        "s3",
        "s3://3dgen-runs/runs",
        env={
            "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
            "R2_ACCESS_KEY_ID": "access-key",
            "R2_SECRET_ACCESS_KEY": "secret-key",
        },
        s3_client=FakeS3Client(),
    )

    assert isinstance(uploader, S3Uploader)
