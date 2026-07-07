from pathlib import Path

import pytest

from bench_harness.uploader import LocalUploader, create_uploader


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


def test_s3_uploader_fails_fast_until_implemented() -> None:
    with pytest.raises(NotImplementedError, match="S3 uploader"):
        create_uploader("s3", "s3://bucket/prefix")
