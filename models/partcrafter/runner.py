from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runner_utils import (
    RuntimeSnapshot,
    TaskDefinition,
    collect_runtime_snapshot,
    load_tasks,
    parse_max_runtime_seconds,
    require_infer_arg,
    require_int,
    required_env,
    run_with_peak_vram,
    should_retry_task_error,
    upload_task_increment_if_configured,
    upload_task_increment_then_raise_timeout,
    utc_now,
    write_task_failure,
)


MODEL_ID = "partcrafter"
MODEL_GIT_COMMIT = "3d773bf02fad51c7ab31a5615573fec93b287b30"
WEIGHTS_REVISION = "69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f"
PARTCRAFTER_ROOT = Path("/opt/PartCrafter")
MAX_TASK_ATTEMPTS = 2

PARTCRAFTER_WEIGHTS_PATH = required_env("PARTCRAFTER_WEIGHTS_PATH")
RMBG_WEIGHTS_PATH = required_env("RMBG_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "num_parts": 3,
    "num_tokens": 1024,
    "num_inference_steps": 50,
    "guidance_scale": 7.0,
    "max_num_expanded_coords": 1000000000,
    "use_flash_decoder": False,
    "rmbg": True,
    "part_suggest": False,
    "style_transfer": False,
    "dtype": "float16",
    "partcrafter_weights_path": PARTCRAFTER_WEIGHTS_PATH,
    "rmbg_weights_path": RMBG_WEIGHTS_PATH,
}

@dataclass(frozen=True)
class LicenseSources:
    root_license: Path
    rmbg_license: Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="partcrafter-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-num-parts", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-num-tokens", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-num-inference-steps", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-guidance-scale", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--infer-max-num-expanded-coords", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-use-flash-decoder", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--infer-partcrafter-weights-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-rmbg-weights-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-rmbg", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_partcrafter_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = LicenseSources(
        root_license=PARTCRAFTER_ROOT / "LICENSE",
        rmbg_license=Path(RMBG_WEIGHTS_PATH) / "README.md",
    )

    for task in tasks:
        remaining = max_runtime_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            raise TimeoutError("MAX_RUNTIME_MIN exceeded before starting next task")
        run_task(task, args.input_root, args.output_root, license_sources, remaining)


def run_task(
    task: TaskDefinition,
    input_root: Path,
    output_root: Path,
    license_sources: LicenseSources,
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
        command = build_partcrafter_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(
                command,
                timeout_seconds,
                "PartCrafter",
                log_path=raw_output_dir / "infer.log",
            )
            wall_clock_seconds = time.monotonic() - started_monotonic
            finished_iso = utc_now()
            runtime = collect_runtime_snapshot(peak_vram_bytes, "sdpa")
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
            if isinstance(exc, TimeoutError):
                upload_task_increment_then_raise_timeout(
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


def build_partcrafter_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    command = [
        "python3",
        "/opt/3dgen-runner/partcrafter_runner.py",
        "--infer-image",
        str(image_path),
        "--infer-output-dir",
        str(raw_output_dir),
        "--infer-seed",
        str(seed),
        "--infer-num-parts",
        str(parameters["num_parts"]),
        "--infer-num-tokens",
        str(parameters["num_tokens"]),
        "--infer-num-inference-steps",
        str(parameters["num_inference_steps"]),
        "--infer-guidance-scale",
        str(parameters["guidance_scale"]),
        "--infer-max-num-expanded-coords",
        str(parameters["max_num_expanded_coords"]),
        "--infer-partcrafter-weights-path",
        str(parameters["partcrafter_weights_path"]),
        "--infer-rmbg-weights-path",
        str(parameters["rmbg_weights_path"]),
    ]
    if parameters["use_flash_decoder"]:
        command.append("--infer-use-flash-decoder")
    if parameters["rmbg"]:
        command.append("--infer-rmbg")
    return command


def run_partcrafter_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_num_parts, "--infer-num-parts")
    require_infer_arg(args.infer_num_tokens, "--infer-num-tokens")
    require_infer_arg(args.infer_num_inference_steps, "--infer-num-inference-steps")
    require_infer_arg(args.infer_guidance_scale, "--infer-guidance-scale")
    require_infer_arg(args.infer_max_num_expanded_coords, "--infer-max-num-expanded-coords")
    require_infer_arg(args.infer_partcrafter_weights_path, "--infer-partcrafter-weights-path")
    require_infer_arg(args.infer_rmbg_weights_path, "--infer-rmbg-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")
    if not 1 <= args.infer_num_parts <= 16:
        raise ValueError("--infer-num-parts must be in [1, 16]")

    sys.path.insert(0, str(PARTCRAFTER_ROOT))

    import numpy as np
    import torch
    from accelerate.utils import set_seed
    from PIL import Image
    from src.models.briarmbg import BriaRMBG
    from src.pipelines.pipeline_partcrafter import PartCrafterPipeline
    from src.utils.data_utils import get_colored_mesh_composition
    from src.utils.image_utils import prepare_image

    device = "cuda"
    dtype = torch.float16
    rmbg_net = None
    if args.infer_rmbg:
        rmbg_net = BriaRMBG.from_pretrained(str(args.infer_rmbg_weights_path)).to(device)
        rmbg_net.eval()
    pipe: PartCrafterPipeline = PartCrafterPipeline.from_pretrained(str(args.infer_partcrafter_weights_path)).to(
        device,
        dtype,
    )
    set_seed(args.infer_seed)

    if args.infer_rmbg:
        img_pil = prepare_image(
            str(args.infer_image),
            bg_color=np.array([1.0, 1.0, 1.0]),
            rmbg_net=rmbg_net,
        )
    else:
        img_pil = Image.open(args.infer_image)

    outputs = pipe(
        image=[img_pil] * args.infer_num_parts,
        attention_kwargs={"num_parts": args.infer_num_parts},
        num_tokens=args.infer_num_tokens,
        generator=torch.Generator(device=pipe.device).manual_seed(args.infer_seed),
        num_inference_steps=args.infer_num_inference_steps,
        guidance_scale=args.infer_guidance_scale,
        max_num_expanded_coords=args.infer_max_num_expanded_coords,
        use_flash_decoder=args.infer_use_flash_decoder,
    ).meshes

    if len(outputs) != args.infer_num_parts:
        raise RuntimeError(f"PartCrafter returned {len(outputs)} meshes for {args.infer_num_parts} requested parts")

    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    for index, mesh in enumerate(outputs):
        validate_generated_mesh(mesh, index)
        mesh.export(args.infer_output_dir / f"part_{index:02}.glb")

    merged_mesh = get_colored_mesh_composition(outputs)
    merged_mesh.export(args.infer_output_dir / "object.glb")
    manifest = {
        "image_path": str(args.infer_image),
        "num_parts": args.infer_num_parts,
        "style_transferred": False,
        "vlm_suggested": False,
        "parts": [{"index": index, "file": f"part_{index:02}.glb"} for index in range(args.infer_num_parts)],
        "composite_file": "object.glb",
    }
    (args.infer_output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def validate_generated_mesh(mesh: Any, index: int) -> None:
    if mesh is None:
        raise RuntimeError(f"PartCrafter returned no mesh for part {index}")
    vertices = getattr(mesh, "vertices", None)
    faces = getattr(mesh, "faces", None)
    if vertices is None or faces is None or len(vertices) < 3 or len(faces) < 1:
        raise RuntimeError(f"PartCrafter returned a degenerate mesh for part {index}")


def prepare_task_output(
    *,
    task: TaskDefinition,
    task_output_dir: Path,
    raw_output_dir: Path,
    license_sources: LicenseSources,
    runtime: RuntimeSnapshot,
    wall_clock_seconds: float,
    retry_count: int,
    started_at: str,
    finished_at: str,
) -> None:
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")
    mesh_path = raw_output_dir / "object.glb"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"PartCrafter did not create expected composite mesh: {mesh_path}")
    validate_partcrafter_raw_output(raw_output_dir)

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
    (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_partcrafter_raw_output(raw_output_dir: Path) -> None:
    manifest_path = raw_output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"PartCrafter did not create expected manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    num_parts = require_int(manifest.get("num_parts"), "manifest.num_parts")
    if num_parts != DEFAULT_PARAMETERS["num_parts"]:
        raise ValueError(f"manifest.num_parts must be {DEFAULT_PARAMETERS['num_parts']}")
    for index in range(num_parts):
        part_path = raw_output_dir / f"part_{index:02}.glb"
        if not part_path.is_file():
            raise FileNotFoundError(f"PartCrafter did not create expected part mesh: {part_path}")


def write_license_bundle(destination: Path, sources: LicenseSources) -> None:
    sections = [
        ("PartCrafter LICENSE", sources.root_license),
        ("BRIA RMBG-1.4 model card and license metadata", sources.rmbg_license),
    ]
    chunks: list[str] = []
    for title, path in sections:
        if not path.is_file():
            raise FileNotFoundError(f"missing license source: {path}")
        chunks.extend([f"# {title}", f"Source: {path}", "", path.read_text(encoding="utf-8").rstrip(), ""])
    destination.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"partcrafter-runner failed: {exc}", file=sys.stderr)
        raise
