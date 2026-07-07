from __future__ import annotations

import argparse
from pathlib import Path

from bench_harness.meta import validate_task_output
from bench_harness.tasks import load_tasks
from bench_harness.uploader import create_uploader


def main() -> None:
    parser = argparse.ArgumentParser(prog="bench-harness")
    subcommands = parser.add_subparsers(dest="command", required=True)

    tasks_validate = subcommands.add_parser("tasks-validate")
    tasks_validate.add_argument("tasks_json", type=Path)

    output_validate = subcommands.add_parser("output-validate")
    output_validate.add_argument("task_output_dir", type=Path)

    upload_local = subcommands.add_parser("upload-local")
    upload_local.add_argument("source_dir", type=Path)
    upload_local.add_argument("target_root")
    upload_local.add_argument("relative_name")

    args = parser.parse_args()
    if args.command == "tasks-validate":
        tasks = load_tasks(args.tasks_json)
        print(f"valid tasks: {len(tasks)}")
    elif args.command == "output-validate":
        meta = validate_task_output(args.task_output_dir)
        print(f"valid output: {meta['model_id']} / {meta['task_id']}")
    elif args.command == "upload-local":
        uploader = create_uploader("local", args.target_root)
        uploaded = uploader.upload_run(args.source_dir, args.relative_name)
        print(uploaded)
