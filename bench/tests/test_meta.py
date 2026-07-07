import json
from pathlib import Path

import pytest

from bench_harness.meta import load_run_metadata, validate_task_output


def _valid_meta() -> dict[str, object]:
    return {
        "task_id": "cartoon-apple",
        "model_id": "triposr",
        "model_git_commit": "107cefdc244c39106fa830359024f6a2f1c78871",
        "weights_revision": "5b521936b01fbe1890f6f9baed0254ab6351c04a",
        "gpu_name": "NVIDIA GeForce RTX 4070 Ti",
        "wall_clock_seconds": 12.5,
        "peak_vram_bytes": 4_294_967_296,
        "seed": 20260708,
        "parameters": {"foreground_ratio": 0.85},
        "retry_count": 0,
        "torch_version": "2.7.1+cu128",
        "torch_cuda_version": "12.8",
        "torch_cuda_arch_list": ["sm_89", "sm_120"],
        "attention_backend": "sdpa",
        "started_at": "2026-07-08T00:00:00Z",
        "finished_at": "2026-07-08T00:00:13Z",
        "license_file": "LICENSE",
    }


def test_validate_task_output_requires_output_glb_meta_and_license(tmp_path: Path) -> None:
    output_dir = tmp_path / "cartoon-apple"
    output_dir.mkdir()
    (output_dir / "output.glb").write_bytes(b"glTF")
    (output_dir / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (output_dir / "meta.json").write_text(json.dumps(_valid_meta()), encoding="utf-8")

    meta = validate_task_output(output_dir)

    assert meta["model_id"] == "triposr"
    assert meta["license_file"] == "LICENSE"


def test_load_run_metadata_rejects_missing_schema_field(tmp_path: Path) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    del meta["torch_version"]
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="torch_version"):
        load_run_metadata(meta_file)


def test_load_run_metadata_rejects_unknown_schema_field(tmp_path: Path) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta["extra"] = "not allowed"
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="extra"):
        load_run_metadata(meta_file)
