from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from runner_utils import (
    LicenseSource,
    RuntimeSnapshot,
    TaskDefinition,
    VramMeasurementError,
    collect_runtime_snapshot,
    load_tasks,
    parse_max_runtime_seconds,
    require_infer_arg,
    require_int,
    required_env,
    run_with_peak_vram,
    should_retry_task_error,
    upload_task_increment_if_configured,
    upload_task_increment_then_raise,
    utc_now,
    write_license_bundle,
    write_task_failure,
)


MODEL_ID = "sf3d"
MODEL_GIT_COMMIT = "ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2"
WEIGHTS_REVISION = "f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778"
DINOV2_LARGE_REVISION = "47b73eefe95e8d44ec3623f8890bd894b6ea2d6c"
OPENCLIP_REVISION = "1a25a446712ba5ee05982a381eed697ef9b435cf"
SF3D_ROOT = Path("/opt/stable-fast-3d")
NOTICE_PATH = Path("/opt/3dgen-runner/sf3d_NOTICE.txt")
MAX_TASK_ATTEMPTS = 1


SF3D_WEIGHTS_PATH = required_env("SF3D_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "device": "cuda",
    "foreground_ratio": 0.85,
    "texture_resolution": 1024,
    "remesh": "none",
    "target_vertex_count": -1,
    "batch_size": 1,
    "dtype": "bfloat16",
    "attention_backend": "torch-default",
    "sf3d_weights_path": SF3D_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="sf3d-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-foreground-ratio", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--infer-texture-resolution", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-remesh", help=argparse.SUPPRESS)
    parser.add_argument("--infer-target-vertex-count", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-sf3d-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_sf3d_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("Stable Fast 3D code license", SF3D_ROOT / "LICENSE.md"),
        LicenseSource("Stable Fast 3D weights license", Path(SF3D_WEIGHTS_PATH) / "LICENSE.md"),
        LicenseSource("Stable Fast 3D attribution notice", NOTICE_PATH),
    ]

    for task in tasks:
        remaining = max_runtime_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            raise TimeoutError("MAX_RUNTIME_MIN exceeded before starting next task")
        run_task(task, args.input_root, args.output_root, license_sources, remaining)


def run_task(
    task: TaskDefinition,
    input_root: Path,
    output_root: Path,
    license_sources: list[LicenseSource],
    timeout_seconds: float,
) -> None:
    image_path = input_root / task.image
    if not image_path.is_file():
        raise FileNotFoundError(f"missing input image for {task.id}: {image_path}")

    task_output_dir = output_root / task.id
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")

    work_dir = output_root / "_work" / MODEL_ID / task.id
    first_started_iso = utc_now()
    for attempt_index in range(MAX_TASK_ATTEMPTS):
        if work_dir.exists():
            shutil.rmtree(work_dir)
        if task_output_dir.exists():
            shutil.rmtree(task_output_dir)
        work_dir.mkdir(parents=True, exist_ok=False)
        raw_output_dir = work_dir / "raw"
        raw_output_dir.mkdir(parents=True, exist_ok=False)

        started_iso = utc_now()
        started_monotonic = time.monotonic()
        command = build_sf3d_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            vram_measurement = run_with_peak_vram(
                command,
                timeout_seconds,
                "Stable Fast 3D",
                log_path=raw_output_dir / "infer.log",
            )
            wall_clock_seconds = time.monotonic() - started_monotonic
            finished_iso = utc_now()
            runtime = collect_runtime_snapshot(vram_measurement, DEFAULT_PARAMETERS["attention_backend"])
            prepare_task_output(
                task=task,
                task_output_dir=task_output_dir,
                raw_output_dir=raw_output_dir,
                license_sources=license_sources,
                runtime=runtime,
                wall_clock_seconds=wall_clock_seconds,
                retry_count=attempt_index,
                started_at=started_iso,
                finished_at=finished_iso,
            )
            shutil.rmtree(work_dir)
        except Exception as exc:
            if work_dir.exists():
                shutil.rmtree(work_dir)
            if task_output_dir.exists():
                shutil.rmtree(task_output_dir)
            if should_retry_task_error(exc, attempt_index, MAX_TASK_ATTEMPTS):
                continue
            write_task_failure(
                task=task,
                task_output_dir=task_output_dir,
                model_id=MODEL_ID,
                model_git_commit=MODEL_GIT_COMMIT,
                weights_revision=WEIGHTS_REVISION,
                parameters=DEFAULT_PARAMETERS,
                error=exc,
                retry_count=attempt_index,
                started_at=first_started_iso,
                finished_at=utc_now(),
            )
            if isinstance(exc, (TimeoutError, VramMeasurementError)):
                upload_task_increment_then_raise(
                    task_output_dir,
                    task.id,
                    os.environ,
                    exc,
                    upload=upload_task_increment_if_configured,
                )
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return
        else:
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return


def build_sf3d_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/sf3d_runner.py",
        "--infer-image",
        image_path.as_posix(),
        "--infer-output-dir",
        raw_output_dir.as_posix(),
        "--infer-seed",
        str(seed),
        "--infer-foreground-ratio",
        str(parameters["foreground_ratio"]),
        "--infer-texture-resolution",
        str(parameters["texture_resolution"]),
        "--infer-remesh",
        str(parameters["remesh"]),
        "--infer-target-vertex-count",
        str(parameters["target_vertex_count"]),
        "--infer-sf3d-weights-path",
        str(parameters["sf3d_weights_path"]),
    ]


def run_sf3d_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_foreground_ratio, "--infer-foreground-ratio")
    require_infer_arg(args.infer_texture_resolution, "--infer-texture-resolution")
    require_infer_arg(args.infer_remesh, "--infer-remesh")
    require_infer_arg(args.infer_target_vertex_count, "--infer-target-vertex-count")
    require_infer_arg(args.infer_sf3d_weights_path, "--infer-sf3d-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")

    texture_resolution = require_int(args.infer_texture_resolution, "--infer-texture-resolution")
    target_vertex_count = require_int(args.infer_target_vertex_count, "--infer-target-vertex-count")
    if args.infer_foreground_ratio != DEFAULT_PARAMETERS["foreground_ratio"]:
        raise ValueError("--infer-foreground-ratio must be 0.85 for the official Stable Fast 3D protocol")
    if texture_resolution != DEFAULT_PARAMETERS["texture_resolution"]:
        raise ValueError("--infer-texture-resolution must be 1024 for the official Stable Fast 3D protocol")
    if args.infer_remesh != DEFAULT_PARAMETERS["remesh"]:
        raise ValueError("--infer-remesh must be none for the official Stable Fast 3D protocol")
    if target_vertex_count != DEFAULT_PARAMETERS["target_vertex_count"]:
        raise ValueError("--infer-target-vertex-count must be -1 for the official Stable Fast 3D protocol")

    weights_path = args.infer_sf3d_weights_path
    for required_file in ("config.yaml", "model.safetensors", "LICENSE.md"):
        path = weights_path / required_file
        if not path.is_file():
            raise FileNotFoundError(f"missing Stable Fast 3D staged file: {path}")

    hf_home = Path(required_env("HF_HOME"))
    require_staged_hf_snapshot(
        hf_home,
        repo_cache_name="models--facebook--dinov2-large",
        revision=DINOV2_LARGE_REVISION,
        required_files=("config.json", "model.safetensors"),
    )
    require_staged_hf_snapshot(
        hf_home,
        repo_cache_name="models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K",
        revision=OPENCLIP_REVISION,
        required_files=("open_clip_config.json", "open_clip_pytorch_model.bin"),
    )

    sys.path.insert(0, str(SF3D_ROOT))

    import rembg
    import torch
    from PIL import Image
    from sf3d.system import SF3D
    from sf3d.utils import remove_background, resize_foreground

    if not torch.cuda.is_available():
        raise RuntimeError("Stable Fast 3D benchmark requires CUDA")
    torch.manual_seed(args.infer_seed)
    torch.cuda.manual_seed_all(args.infer_seed)

    model = SF3D.from_pretrained(
        str(weights_path),
        config_name="config.yaml",
        weight_name="model.safetensors",
    )
    model.to("cuda")
    model.eval()

    rembg_session = rembg.new_session("u2net")
    image = remove_background(Image.open(args.infer_image).convert("RGBA"), rembg_session)
    image = resize_foreground(image, args.infer_foreground_ratio)

    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    image.save(args.infer_output_dir / "input.png")
    autocast = torch.autocast(device_type="cuda", dtype=torch.bfloat16)
    with torch.no_grad():
        with autocast if torch.cuda.is_available() else nullcontext():
            mesh, _ = model.run_image(
                image,
                bake_resolution=texture_resolution,
                remesh=args.infer_remesh,
                vertex_count=target_vertex_count,
            )
    mesh.export(args.infer_output_dir / "output.glb", include_normals=True)

    overrides = {
        "foreground_ratio": args.infer_foreground_ratio,
        "remesh": args.infer_remesh,
        "seed": args.infer_seed,
        "sf3d_weights_path": str(weights_path),
        "target_vertex_count": target_vertex_count,
        "texture_resolution": texture_resolution,
    }
    (args.infer_output_dir / "inference_overrides.json").write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def require_staged_hf_snapshot(
    hf_home: Path,
    *,
    repo_cache_name: str,
    revision: str,
    required_files: tuple[str, ...],
) -> Path:
    repo_cache = hf_home / "hub" / repo_cache_name
    main_ref = repo_cache / "refs" / "main"
    if not main_ref.is_file():
        raise FileNotFoundError(f"missing staged Hugging Face main ref: {main_ref}")
    actual_revision = main_ref.read_text(encoding="utf-8").strip()
    if actual_revision != revision:
        raise ValueError(f"unexpected staged Hugging Face revision for {repo_cache_name}: {actual_revision}")
    snapshot = repo_cache / "snapshots" / revision
    for required_file in required_files:
        path = snapshot / required_file
        if not path.is_file():
            raise FileNotFoundError(f"missing staged Hugging Face file: {path}")
    return snapshot


def prepare_task_output(
    *,
    task: TaskDefinition,
    task_output_dir: Path,
    raw_output_dir: Path,
    license_sources: list[LicenseSource],
    runtime: RuntimeSnapshot,
    wall_clock_seconds: float,
    retry_count: int,
    started_at: str,
    finished_at: str,
) -> None:
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")
    mesh_path = raw_output_dir / "output.glb"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"Stable Fast 3D did not create expected GLB: {mesh_path}")

    task_output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(mesh_path, task_output_dir / "output.glb")
    shutil.copytree(raw_output_dir, task_output_dir / "raw" / MODEL_ID)
    write_license_bundle(task_output_dir / "LICENSES.txt", license_sources)
    meta = {
        "task_id": task.id,
        "model_id": MODEL_ID,
        "model_git_commit": MODEL_GIT_COMMIT,
        "weights_revision": WEIGHTS_REVISION,
        "gpu_name": runtime.gpu_name,
        "wall_clock_seconds": wall_clock_seconds,
        "peak_vram_bytes": runtime.peak_vram_bytes,
        "vram_measurement": runtime.vram.to_meta(),
        "seed": task.seed,
        "parameters": DEFAULT_PARAMETERS,
        "retry_count": retry_count,
        "torch_version": runtime.torch_version,
        "torch_cuda_version": runtime.torch_cuda_version,
        "torch_cuda_arch_list": runtime.torch_cuda_arch_list,
        "attention_backend": runtime.attention_backend,
        "started_at": started_at,
        "finished_at": finished_at,
        "license_file": "LICENSES.txt",
    }
    (task_output_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"sf3d-runner failed: {exc}", file=sys.stderr)
        raise
