from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn, Sequence

from bench_harness.runpod_runtime import CloudRuntimeConfig, run_cloud_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bench_harness.container_entrypoint")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--runner-path", type=Path, required=True)
    parser.add_argument("mode", choices=("runner", "runpod"))
    parser.add_argument("mode_args", nargs=argparse.REMAINDER)
    return parser


def build_runpod_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bench_harness.container_entrypoint ... runpod")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--s3-target", required=True)
    parser.add_argument("runner_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    model_id = args.model_id.strip()
    if not model_id:
        parser.error("--model-id must be non-empty")
    runner_path = args.runner_path
    if not runner_path.is_absolute():
        parser.error("--runner-path must be absolute")
    if not runner_path.is_file():
        parser.error(f"runner does not exist: {runner_path}")

    if args.mode == "runner":
        exec_runner(runner_path, args.mode_args)

    runpod_parser = build_runpod_parser()
    runpod_args = runpod_parser.parse_args(args.mode_args)
    if runpod_args.runner_args[:1] != ["--"]:
        runpod_parser.error("runner arguments must follow --")
    runner_command = (sys.executable, str(runner_path), *runpod_args.runner_args[1:])
    exit_code = run_cloud_runtime(
        CloudRuntimeConfig(
            model_id=model_id,
            output_root=runpod_args.output_root,
            s3_target=runpod_args.s3_target,
            runner_command=runner_command,
        )
    )
    raise SystemExit(exit_code)


def exec_runner(runner_path: Path, runner_args: Sequence[str]) -> NoReturn:
    command = [sys.executable, str(runner_path), *runner_args]
    os.execv(sys.executable, command)
    raise RuntimeError("runner exec returned unexpectedly")


if __name__ == "__main__":
    main()
