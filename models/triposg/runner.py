from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL_ID = "triposg"
MODEL_GIT_COMMIT = "fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c"
WEIGHTS_REVISION = "2c1c516d22d58db486a058d98d31bb6177344e06"
RUNPOD_USER_AGENT = "3dgen-demoroom-bench-harness/0.1"
TRIPOSG_ROOT = Path("/opt/TripoSG")
LICENSE_SOURCES = None
MAX_TASK_ATTEMPTS = 2


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


TRIPOSG_WEIGHTS_PATH = required_env("TRIPOSG_WEIGHTS_PATH")
RMBG_WEIGHTS_PATH = required_env("RMBG_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "num_inference_steps": 50,
    "num_tokens": 2048,
    "guidance_scale": 7.0,
    "dense_octree_depth": 8,
    "hierarchical_octree_depth": 9,
    "flash_octree_depth": 9,
    "use_flash_decoder": True,
    "faces": -1,
    "dtype": "float16",
    "triposg_weights_path": TRIPOSG_WEIGHTS_PATH,
    "rmbg_weights_path": RMBG_WEIGHTS_PATH,
}

REQUIRED_TASK_KEYS = frozenset({"id", "prompt", "image", "seed"})


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    prompt: str
    image: str
    seed: int


@dataclass(frozen=True)
class RuntimeSnapshot:
    gpu_name: str
    peak_vram_bytes: int
    torch_version: str
    torch_cuda_version: str
    torch_cuda_arch_list: list[str]
    attention_backend: str


@dataclass(frozen=True)
class LicenseSources:
    root_license: Path
    notice: Path
    bundled_license: Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="triposg-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-num-inference-steps", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-num-tokens", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-guidance-scale", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--infer-dense-octree-depth", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-hierarchical-octree-depth", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-flash-octree-depth", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-use-flash-decoder", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--infer-faces", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-triposg-weights-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-rmbg-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_triposg_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = LicenseSources(
        root_license=TRIPOSG_ROOT / "LICENSE",
        notice=TRIPOSG_ROOT / "NOTICE",
        bundled_license=TRIPOSG_ROOT / "triposg" / "LICENSE",
    )

    for task in tasks:
        remaining = max_runtime_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            terminate_runpod_if_needed(os.environ)
            raise TimeoutError("MAX_RUNTIME_MIN exceeded before starting next task")
        run_task(task, args.input_root, args.output_root, license_sources, remaining)


def load_tasks(path: Path) -> list[TaskDefinition]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")
    tasks: list[TaskDefinition] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"task[{index}] must be an object")
        keys = set(item)
        missing = REQUIRED_TASK_KEYS - keys
        unknown = keys - REQUIRED_TASK_KEYS
        if missing:
            raise ValueError(f"task[{index}] missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"task[{index}] unknown field(s): {', '.join(sorted(unknown))}")
        task = TaskDefinition(
            id=require_string(item["id"], f"task[{index}].id"),
            prompt=require_string(item["prompt"], f"task[{index}].prompt"),
            image=require_string(item["image"], f"task[{index}].image"),
            seed=require_int(item["seed"], f"task[{index}].seed"),
        )
        if task.id in seen:
            raise ValueError(f"duplicate task id: {task.id}")
        seen.add(task.id)
        tasks.append(task)
    return tasks


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
        command = build_triposg_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(command, timeout_seconds)
            wall_clock_seconds = time.monotonic() - started_monotonic
            finished_iso = utc_now()
            runtime = collect_runtime_snapshot(peak_vram_bytes)
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
            if attempt_index + 1 < MAX_TASK_ATTEMPTS:
                continue
            write_task_failure(
                task=task,
                task_output_dir=task_output_dir,
                error=exc,
                retry_count=attempt_index,
                started_at=first_started_iso,
                finished_at=utc_now(),
            )
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return
        else:
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return


def upload_task_increment_if_configured(task_output_dir: Path, task_id: str, env: dict[str, str]) -> list[str]:
    target = env.get("RUNPOD_INCREMENTAL_S3_TARGET")
    if not target:
        return []
    from bench_harness.uploader import create_uploader

    uploader = create_uploader("s3", target, env=env)
    return uploader.upload_run(task_output_dir, task_id)


def write_task_failure(
    *,
    task: TaskDefinition,
    task_output_dir: Path,
    error: Exception,
    retry_count: int,
    started_at: str,
    finished_at: str,
) -> None:
    task_output_dir.mkdir(parents=True, exist_ok=False)
    failure = {
        "status": "failed",
        "task_id": task.id,
        "model_id": MODEL_ID,
        "model_git_commit": MODEL_GIT_COMMIT,
        "weights_revision": WEIGHTS_REVISION,
        "seed": task.seed,
        "parameters": DEFAULT_PARAMETERS,
        "retry_count": retry_count,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    (task_output_dir / "failure.json").write_text(
        json.dumps(failure, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_triposg_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    command = [
        "python3",
        "/opt/3dgen-runner/triposg_runner.py",
        "--infer-image",
        str(image_path),
        "--infer-output-path",
        str(raw_output_dir / "output.glb"),
        "--infer-seed",
        str(seed),
        "--infer-num-inference-steps",
        str(parameters["num_inference_steps"]),
        "--infer-num-tokens",
        str(parameters["num_tokens"]),
        "--infer-guidance-scale",
        str(parameters["guidance_scale"]),
        "--infer-dense-octree-depth",
        str(parameters["dense_octree_depth"]),
        "--infer-hierarchical-octree-depth",
        str(parameters["hierarchical_octree_depth"]),
        "--infer-flash-octree-depth",
        str(parameters["flash_octree_depth"]),
    ]
    if parameters["use_flash_decoder"]:
        command.append("--infer-use-flash-decoder")
    command += [
        "--infer-faces",
        str(parameters["faces"]),
        "--infer-triposg-weights-path",
        str(parameters["triposg_weights_path"]),
        "--infer-rmbg-weights-path",
        str(parameters["rmbg_weights_path"]),
    ]
    return command


def run_triposg_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_path, "--infer-output-path")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_num_inference_steps, "--infer-num-inference-steps")
    require_infer_arg(args.infer_num_tokens, "--infer-num-tokens")
    require_infer_arg(args.infer_guidance_scale, "--infer-guidance-scale")
    require_infer_arg(args.infer_dense_octree_depth, "--infer-dense-octree-depth")
    require_infer_arg(args.infer_hierarchical_octree_depth, "--infer-hierarchical-octree-depth")
    require_infer_arg(args.infer_flash_octree_depth, "--infer-flash-octree-depth")
    require_infer_arg(args.infer_faces, "--infer-faces")
    require_infer_arg(args.infer_triposg_weights_path, "--infer-triposg-weights-path")
    require_infer_arg(args.infer_rmbg_weights_path, "--infer-rmbg-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")

    sys.path.insert(0, str(TRIPOSG_ROOT))
    sys.path.insert(0, str(TRIPOSG_ROOT / "scripts"))

    import numpy as np
    import torch
    import trimesh
    from briarmbg import BriaRMBG
    from image_process import prepare_image
    from triposg.pipelines.pipeline_triposg import TripoSGPipeline

    device = "cuda"
    dtype = torch.float16
    rmbg_net = BriaRMBG.from_pretrained(str(args.infer_rmbg_weights_path)).to(device)
    rmbg_net.eval()
    pipe: TripoSGPipeline = TripoSGPipeline.from_pretrained(str(args.infer_triposg_weights_path)).to(device, dtype)

    img_pil = prepare_image(
        str(args.infer_image),
        bg_color=np.array([1.0, 1.0, 1.0]),
        rmbg_net=rmbg_net,
    )
    outputs = pipe(
        image=img_pil,
        generator=torch.Generator(device=pipe.device).manual_seed(args.infer_seed),
        num_inference_steps=args.infer_num_inference_steps,
        num_tokens=args.infer_num_tokens,
        guidance_scale=args.infer_guidance_scale,
        dense_octree_depth=args.infer_dense_octree_depth,
        hierarchical_octree_depth=args.infer_hierarchical_octree_depth,
        flash_octree_depth=args.infer_flash_octree_depth,
        use_flash_decoder=args.infer_use_flash_decoder,
    ).samples[0]
    mesh = trimesh.Trimesh(outputs[0].astype(np.float32), np.ascontiguousarray(outputs[1]))
    if args.infer_faces > 0:
        mesh = simplify_mesh(mesh, args.infer_faces)
    args.infer_output_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(args.infer_output_path)


def simplify_mesh(mesh: Any, n_faces: int) -> Any:
    if mesh.faces.shape[0] <= n_faces:
        return mesh

    import pymeshlab
    import trimesh

    mesh_set = pymeshlab.MeshSet()
    mesh_set.add_mesh(pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces))
    mesh_set.meshing_merge_close_vertices()
    mesh_set.meshing_decimation_quadric_edge_collapse(targetfacenum=n_faces)
    current = mesh_set.current_mesh()
    return trimesh.Trimesh(vertices=current.vertex_matrix(), faces=current.face_matrix())


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
    mesh_path = raw_output_dir / "output.glb"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"TripoSG did not create expected mesh: {mesh_path}")

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


def write_license_bundle(destination: Path, sources: LicenseSources) -> None:
    sections = [
        ("TripoSG root LICENSE", sources.root_license),
        ("TripoSG NOTICE", sources.notice),
        ("TripoSG bundled model LICENSE", sources.bundled_license),
    ]
    chunks: list[str] = []
    for title, path in sections:
        if not path.is_file():
            raise FileNotFoundError(f"missing license source: {path}")
        chunks.extend([f"# {title}", f"Source: {path}", "", path.read_text(encoding="utf-8").rstrip(), ""])
    destination.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")


def collect_runtime_snapshot(peak_vram_bytes: int) -> RuntimeSnapshot:
    import torch

    return RuntimeSnapshot(
        gpu_name=query_gpu_name(),
        peak_vram_bytes=peak_vram_bytes,
        torch_version=torch.__version__,
        torch_cuda_version=str(torch.version.cuda),
        torch_cuda_arch_list=list(torch.cuda.get_arch_list()),
        attention_backend="sdpa",
    )


def run_with_peak_vram(command: list[str], timeout_seconds: float) -> int:
    process = subprocess.Popen(command)
    deadline = time.monotonic() + timeout_seconds
    peak_mib = query_gpu_memory_mib()
    while process.poll() is None:
        if time.monotonic() >= deadline:
            process.kill()
            terminate_runpod_if_needed(os.environ)
            raise TimeoutError("MAX_RUNTIME_MIN exceeded while running TripoSG")
        peak_mib = max(peak_mib, query_gpu_memory_mib())
        time.sleep(0.5)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
    return peak_mib * 1024 * 1024


def query_gpu_memory_mib() -> int:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        text=True,
    )
    values = [int(line.strip()) for line in output.splitlines() if line.strip()]
    if not values:
        raise RuntimeError("nvidia-smi returned no GPU memory values")
    return max(values)


def query_gpu_name() -> str:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        text=True,
    )
    names = [line.strip() for line in output.splitlines() if line.strip()]
    if not names:
        raise RuntimeError("nvidia-smi returned no GPU name")
    return names[0]


def parse_max_runtime_seconds(env: dict[str, str]) -> int:
    raw_value = env.get("MAX_RUNTIME_MIN")
    if raw_value is None:
        return 60 * 60
    minutes = require_int(raw_value, "MAX_RUNTIME_MIN")
    if minutes <= 0:
        raise ValueError("MAX_RUNTIME_MIN must be a positive integer")
    return minutes * 60


def terminate_runpod_if_needed(env: dict[str, str]) -> None:
    pod_id = env.get("RUNPOD_POD_ID")
    if not pod_id:
        return
    api_key = env.get("RUNPOD_API_KEY")
    if not api_key:
        raise ValueError("RUNPOD_API_KEY is required when RUNPOD_POD_ID is set")

    import urllib.request

    request = urllib.request.Request(
        f"https://rest.runpod.io/v1/pods/{pod_id}",
        method="DELETE",
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": RUNPOD_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"RunPod termination failed with HTTP {response.status}")


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def require_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def require_infer_arg(value: Any, flag: str) -> None:
    if value is None:
        raise ValueError(f"{flag} is required in infer mode")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"triposg-runner failed: {exc}", file=sys.stderr)
        raise
