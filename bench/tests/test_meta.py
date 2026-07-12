import json
import struct
from pathlib import Path

import pytest

from bench_harness.meta import load_run_failure, load_run_metadata, validate_glb, validate_task_output


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


def _valid_failure() -> dict[str, object]:
    return {
        "status": "failed",
        "task_id": "cartoon-apple",
        "model_id": "triposr",
        "model_git_commit": "107cefdc244c39106fa830359024f6a2f1c78871",
        "weights_revision": "5b521936b01fbe1890f6f9baed0254ab6351c04a",
        "seed": 20260708,
        "parameters": {"foreground_ratio": 0.85},
        "retry_count": 1,
        "error_type": "RuntimeError",
        "error_message": "inference failed",
        "started_at": "2026-07-08T00:00:00Z",
        "finished_at": "2026-07-08T00:00:13Z",
    }


def _valid_process_vram_measurement() -> dict[str, object]:
    return {
        "schema_version": 1,
        "method": "nvidia_smi_compute_process_mib_sampled_sum",
        "scope": "inference_process_group",
        "gpu_uuid": "GPU-11111111-2222-3333-4444-555555555555",
        "gpu_index": 0,
        "cuda_device_ordinal": 0,
        "root_pid": 1234,
        "sample_interval_ms": 500,
        "sample_count": 12,
        "max_matched_process_count": 3,
        "pid_namespace_verified": True,
        "device_baseline_bytes": 0,
        "device_baseline_included": False,
        "co_resident_processes_included": False,
    }


def _valid_runpod_vram_measurement() -> dict[str, object]:
    measurement = _valid_process_vram_measurement()
    measurement.update(
        {
            "method": "nvidia_smi_device_memory_mib_sampled",
            "scope": "runpod_exclusive_device",
            "max_matched_process_count": 0,
            "pid_namespace_verified": False,
            "device_baseline_bytes": 268_435_456,
            "device_baseline_included": True,
            "co_resident_processes_included": True,
        }
    )
    return measurement


def _write_minimal_glb(path: Path) -> None:
    _write_glb_json(path, b'{"asset":{"version":"2.0"}}')


def _write_glb_json(path: Path, json_chunk: bytes) -> None:
    json_chunk += b" " * (-len(json_chunk) % 4)
    total_size = 12 + 8 + len(json_chunk)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_size)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
    )


def test_validate_task_output_requires_output_glb_meta_and_license(tmp_path: Path) -> None:
    output_dir = tmp_path / "cartoon-apple"
    output_dir.mkdir()
    _write_minimal_glb(output_dir / "output.glb")
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


def test_load_run_metadata_accepts_without_optional_fields(tmp_path: Path) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    assert load_run_metadata(meta_file) == meta


def test_load_run_metadata_accepts_external_revision_fields(tmp_path: Path) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta["external_weight_revisions"] = {
        "briaai/RMBG-2.0": "5df4c9c76d8170882c34f6986e848ee07fd0ba43"
    }
    meta["external_code_revisions"] = {
        "microsoft/MoGe": "07444410f1e33f402353b99d6ccd26bd31e469e8"
    }
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    assert load_run_metadata(meta_file) == meta


@pytest.mark.parametrize(
    "measurement",
    [_valid_process_vram_measurement(), _valid_runpod_vram_measurement()],
)
def test_load_run_metadata_accepts_explicit_vram_measurement_scope(
    tmp_path: Path,
    measurement: dict[str, object],
) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta["vram_measurement"] = measurement
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    assert load_run_metadata(meta_file) == meta


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("gpu_uuid"), "missing field"),
        (lambda value: value.update({"unexpected": True}), "unknown field"),
        (lambda value: value.update({"gpu_uuid": "GPU-short"}), "full GPU UUID"),
        (lambda value: value.update({"sample_interval_ms": 100}), "sample_interval_ms"),
        (lambda value: value.update({"pid_namespace_verified": False}), "flags"),
        (lambda value: value.update({"method": "device-total"}), "supported pair"),
    ],
)
def test_load_run_metadata_rejects_invalid_vram_measurement_contract(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    measurement = _valid_process_vram_measurement()
    mutation(measurement)
    meta["vram_measurement"] = measurement
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_run_metadata(meta_file)


def test_load_run_metadata_rejects_unknown_schema_field(tmp_path: Path) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta["extra"] = "not allowed"
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="extra"):
        load_run_metadata(meta_file)


def test_load_run_metadata_rejects_invalid_optional_revision_map(tmp_path: Path) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta["external_weight_revisions"] = {"repo": 42}
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="external_weight_revisions"):
        load_run_metadata(meta_file)


def test_load_run_failure_validates_exact_schema(tmp_path: Path) -> None:
    failure_file = tmp_path / "failure.json"
    failure = _valid_failure()
    failure["error_returncode"] = -9
    failure["error_output_tail"] = "CUDA out of memory"
    failure_file.write_text(json.dumps(failure), encoding="utf-8")

    assert load_run_failure(failure_file) == failure


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "error", "status"),
        ("retry_count", "1", "retry_count"),
        ("started_at", "not-a-time", "started_at"),
    ],
)
def test_load_run_failure_rejects_invalid_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    failure_file = tmp_path / "failure.json"
    failure = _valid_failure()
    failure[field] = value
    failure_file.write_text(json.dumps(failure), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_run_failure(failure_file)


def test_load_run_failure_rejects_unknown_schema_field(tmp_path: Path) -> None:
    failure_file = tmp_path / "failure.json"
    failure = _valid_failure()
    failure["unexpected"] = True
    failure_file.write_text(json.dumps(failure), encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected"):
        load_run_failure(failure_file)


def test_validate_task_output_rejects_invalid_glb_length(tmp_path: Path) -> None:
    output_dir = tmp_path / "cartoon-apple"
    output_dir.mkdir()
    (output_dir / "output.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 99))
    (output_dir / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (output_dir / "meta.json").write_text(json.dumps(_valid_meta()), encoding="utf-8")

    with pytest.raises(ValueError, match="declares 99 bytes"):
        validate_task_output(output_dir)


def test_validate_task_output_rejects_header_only_glb(tmp_path: Path) -> None:
    output_dir = tmp_path / "cartoon-apple"
    output_dir.mkdir()
    (output_dir / "output.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
    (output_dir / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (output_dir / "meta.json").write_text(json.dumps(_valid_meta()), encoding="utf-8")

    with pytest.raises(ValueError, match="missing a GLB JSON chunk"):
        validate_task_output(output_dir)


def test_validate_task_output_rejects_license_alias_to_glb(tmp_path: Path) -> None:
    output_dir = tmp_path / "cartoon-apple"
    output_dir.mkdir()
    _write_minimal_glb(output_dir / "output.glb")
    meta = _valid_meta()
    meta["license_file"] = "output.glb"
    (output_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="independent text artifact"):
        validate_task_output(output_dir)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_load_run_metadata_rejects_non_finite_number(tmp_path: Path, value: float) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta["wall_clock_seconds"] = value
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="finite"):
        load_run_metadata(meta_file)


def test_load_run_metadata_rejects_empty_cuda_arch_list(tmp_path: Path) -> None:
    meta_file = tmp_path / "meta.json"
    meta = _valid_meta()
    meta["torch_cuda_arch_list"] = []
    meta_file.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty string array"):
        load_run_metadata(meta_file)


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_validate_glb_rejects_non_standard_json_constants(tmp_path: Path, constant: bytes) -> None:
    glb_path = tmp_path / "invalid.glb"
    _write_glb_json(glb_path, b'{"asset":{"version":"2.0"},"scene":' + constant + b"}")

    with pytest.raises(ValueError, match="invalid GLB JSON"):
        validate_glb(glb_path)
