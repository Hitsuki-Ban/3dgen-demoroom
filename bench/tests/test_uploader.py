from pathlib import Path

import pytest

from bench_harness.uploader import LocalUploader, S3UploadConfig, S3Uploader, create_uploader


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


class FakeS3Client:
    def __init__(self, objects: set[str] | None = None) -> None:
        self.uploads: list[tuple[str, str, str]] = []
        self.objects = set(objects or ())
        self.deleted: list[list[str]] = []

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((filename, bucket, key))
        self.objects.add(key)

    def list_objects_v2(self, **request):
        prefix = request["Prefix"]
        return {
            "Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(prefix)],
            "IsTruncated": False,
        }

    def delete_objects(self, *, Bucket: str, Delete: dict[str, object]) -> None:
        keys = [item["Key"] for item in Delete["Objects"]]
        self.deleted.append(keys)
        self.objects.difference_update(keys)


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


def test_s3_uploader_uploads_files_with_relative_keys(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "cartoon-apple" / "raw").mkdir(parents=True)
    (source / "cartoon-apple" / "output.glb").write_bytes(b"glTF")
    (source / "cartoon-apple" / "raw" / "mesh.glb").write_bytes(b"raw")
    fake_client = FakeS3Client()
    uploader = S3Uploader(
        S3UploadConfig(
            bucket="3dgen-runs",
            prefix="runs",
            endpoint_url="https://example.r2.cloudflarestorage.com",
            access_key_id="access-key",
            secret_access_key="secret-key",
        ),
        client=fake_client,
    )

    uploaded = uploader.upload_run(source, "triposg/rtx-5090/20260708T000000Z")

    assert uploaded == [
        "runs/triposg/rtx-5090/20260708T000000Z/cartoon-apple/output.glb",
        "runs/triposg/rtx-5090/20260708T000000Z/cartoon-apple/raw/mesh.glb",
    ]
    assert fake_client.uploads == [
        (
            str(source / "cartoon-apple" / "output.glb"),
            "3dgen-runs",
            "runs/triposg/rtx-5090/20260708T000000Z/cartoon-apple/output.glb",
        ),
        (
            str(source / "cartoon-apple" / "raw" / "mesh.glb"),
            "3dgen-runs",
            "runs/triposg/rtx-5090/20260708T000000Z/cartoon-apple/raw/mesh.glb",
        ),
    ]


def test_s3_uploader_omits_dot_segment_when_relative_name_is_empty(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "probe.txt").write_text("probe\n", encoding="utf-8")
    fake_client = FakeS3Client()
    uploader = S3Uploader(
        S3UploadConfig(
            bucket="3dgen-runs",
            prefix="_codex-s3-probe",
            endpoint_url="https://example.r2.cloudflarestorage.com",
            access_key_id="access-key",
            secret_access_key="secret-key",
        ),
        client=fake_client,
    )

    uploaded = uploader.upload_run(source)

    assert uploaded == ["_codex-s3-probe/probe.txt"]
    assert fake_client.uploads == [
        (str(source / "probe.txt"), "3dgen-runs", "_codex-s3-probe/probe.txt")
    ]


def test_s3_uploader_replaces_existing_task_prefix_before_retry_upload(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "failure.json").write_text("{}\n", encoding="utf-8")
    old_keys = {
        "runs/retry-task/LICENSES.txt",
        "runs/retry-task/meta.json",
        "runs/retry-task/output.glb",
        "runs/retry-task/raw/mesh.glb",
        "runs/other-task/meta.json",
    }
    fake_client = FakeS3Client(old_keys)
    uploader = S3Uploader(
        S3UploadConfig(
            bucket="3dgen-runs",
            prefix="runs",
            endpoint_url="https://example.r2.cloudflarestorage.com",
            access_key_id="access-key",
            secret_access_key="secret-key",
        ),
        client=fake_client,
    )

    uploaded = uploader.upload_run(source, "retry-task")

    assert uploaded == ["runs/retry-task/failure.json"]
    assert fake_client.deleted == [[
        "runs/retry-task/LICENSES.txt",
        "runs/retry-task/meta.json",
        "runs/retry-task/output.glb",
        "runs/retry-task/raw/mesh.glb",
    ]]
    assert fake_client.objects == {"runs/retry-task/failure.json", "runs/other-task/meta.json"}


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
