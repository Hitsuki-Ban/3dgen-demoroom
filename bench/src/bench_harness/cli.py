from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from bench_harness.meta import validate_task_output
from bench_harness.runpod import (
    DEFAULT_ALLOWED_CUDA_VERSIONS,
    DEFAULT_GPU_TYPE_IDS,
    DEFAULT_MAX_RUNTIME_MIN,
    DEFAULT_MIN_BALANCE_USD,
    R2Credentials,
    RunPodClient,
    RunPodLaunchConfig,
)
from bench_harness.site_data import build_site_manifest, parse_expected_failures
from bench_harness.tasks import load_tasks
from bench_harness.uploader import create_uploader


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def parse_min_balance_usd(raw_value: str | None) -> float:
    if raw_value is None:
        return DEFAULT_MIN_BALANCE_USD
    try:
        balance = float(raw_value)
    except ValueError as exc:
        raise ValueError("RunPod minimum balance must be numeric") from exc
    if balance <= 0:
        raise ValueError("RunPod minimum balance must be positive")
    return balance


def strip_runpod_env(response):
    if isinstance(response, list):
        return [strip_runpod_env(item) for item in response]
    if isinstance(response, dict):
        return {key: strip_runpod_env(value) for key, value in response.items() if key != "env"}
    return response


def main() -> None:
    parser = argparse.ArgumentParser(prog="bench-harness")
    subcommands = parser.add_subparsers(dest="command", required=True)

    tasks_validate = subcommands.add_parser("tasks-validate")
    tasks_validate.add_argument("tasks_json", type=Path)

    output_validate = subcommands.add_parser("output-validate")
    output_validate.add_argument("task_output_dir", type=Path)

    site_data_snapshot = subcommands.add_parser("site-data-snapshot")
    site_data_snapshot.add_argument("runs_root", type=Path)
    site_data_snapshot.add_argument("tasks_json", type=Path)
    site_data_snapshot.add_argument("model_registry", type=Path)
    site_data_snapshot.add_argument("output_path", type=Path)
    site_data_snapshot.add_argument("--expected-failure", action="append", required=True)

    upload_local = subcommands.add_parser("upload-local")
    upload_local.add_argument("source_dir", type=Path)
    upload_local.add_argument("target_root")
    upload_local.add_argument("relative_name")

    upload_s3 = subcommands.add_parser("upload-s3")
    upload_s3.add_argument("source_dir", type=Path)
    upload_s3.add_argument("target_uri")

    runpod_launch = subcommands.add_parser("runpod-launch")
    runpod_launch.add_argument("model_id")
    runpod_launch.add_argument("image_name")
    runpod_launch.add_argument("s3_target")
    runpod_launch.add_argument("--name", required=True)
    runpod_launch.add_argument("--min-balance-usd")
    runpod_launch.add_argument("--max-runtime-min", type=int, default=DEFAULT_MAX_RUNTIME_MIN)
    runpod_launch.add_argument("--gpu-type-id", dest="gpu_type_ids", action="append")
    runpod_launch.add_argument("--allowed-cuda-version", dest="allowed_cuda_versions", action="append")
    runpod_launch.add_argument("--container-registry-auth-id")
    runpod_launch.add_argument("--network-volume-id", required=True)
    runpod_launch.add_argument("--data-center-id", required=True)
    runpod_launch.add_argument("--startup-timeout-min", type=int, required=True)
    task_selection = runpod_launch.add_mutually_exclusive_group()
    task_selection.add_argument("--task-limit", type=int)
    task_selection.add_argument("--task-id", dest="task_ids", action="append")
    runpod_launch.add_argument("--retry-count", type=int, default=0)

    subcommands.add_parser("runpod-pods")

    runpod_terminate = subcommands.add_parser("runpod-terminate")
    runpod_terminate.add_argument("pod_id")

    args = parser.parse_args()
    if args.command == "tasks-validate":
        tasks = load_tasks(args.tasks_json)
        print(f"valid tasks: {len(tasks)}")
    elif args.command == "output-validate":
        meta = validate_task_output(args.task_output_dir)
        print(f"valid output: {meta['model_id']} / {meta['task_id']}")
    elif args.command == "site-data-snapshot":
        expected_failures = parse_expected_failures(args.expected_failure)
        manifest = build_site_manifest(
            runs_root=args.runs_root,
            tasks_json=args.tasks_json,
            model_registry=args.model_registry,
            output_path=args.output_path,
            expected_failures=expected_failures,
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        failure_entries = [entry for entry in manifest["entries"] if entry["status"] == "failed"]
        success_count = len(manifest["entries"]) - len(failure_entries)
        model_count = len({entry["modelId"] for entry in manifest["entries"]})
        task_count = len({entry["taskId"] for entry in manifest["entries"]})
        print(
            f"site-data snapshot: models={model_count} tasks={task_count} cells={len(manifest['entries'])} "
            f"successes={success_count} failures={len(failure_entries)}"
        )
        for entry in failure_entries:
            print(f"failure: {entry['modelId']}/{entry['taskId']}")
    elif args.command == "upload-local":
        uploader = create_uploader("local", args.target_root)
        uploaded = uploader.upload_run(args.source_dir, args.relative_name)
        print(uploaded)
    elif args.command == "upload-s3":
        uploader = create_uploader("s3", args.target_uri)
        uploaded = uploader.upload_run(args.source_dir)
        print(f"uploaded objects: {len(uploaded)}")
    elif args.command == "runpod-launch":
        api_key = required_env("RUNPOD_API_KEY")
        config = RunPodLaunchConfig(
            name=args.name,
            image_name=args.image_name,
            model_id=args.model_id,
            s3_target=args.s3_target,
            max_runtime_min=args.max_runtime_min,
            gpu_type_ids=tuple(args.gpu_type_ids or DEFAULT_GPU_TYPE_IDS),
            allowed_cuda_versions=tuple(args.allowed_cuda_versions or DEFAULT_ALLOWED_CUDA_VERSIONS),
            r2_credentials=R2Credentials.from_env(os.environ),
            container_registry_auth_id=args.container_registry_auth_id,
            network_volume_id=args.network_volume_id,
            data_center_id=args.data_center_id,
            startup_timeout_min=args.startup_timeout_min,
            task_limit=args.task_limit,
            task_ids=tuple(args.task_ids or ()),
            retry_count=args.retry_count,
        )
        min_balance_usd = parse_min_balance_usd(
            args.min_balance_usd if args.min_balance_usd is not None else os.environ.get("RUNPOD_MIN_BALANCE_USD")
        )
        pod = RunPodClient(api_key=api_key).launch_pod(config, min_balance_usd=min_balance_usd)
        print(json.dumps(strip_runpod_env(pod), sort_keys=True))
    elif args.command == "runpod-pods":
        pods = RunPodClient(api_key=required_env("RUNPOD_API_KEY")).list_pods()
        print(json.dumps(strip_runpod_env(pods), sort_keys=True))
    elif args.command == "runpod-terminate":
        pod = RunPodClient(api_key=required_env("RUNPOD_API_KEY")).terminate_pod(args.pod_id)
        print(json.dumps(pod, sort_keys=True))


if __name__ == "__main__":
    main()
