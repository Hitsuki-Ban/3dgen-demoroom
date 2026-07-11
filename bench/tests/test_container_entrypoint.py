import sys
from pathlib import Path

import pytest

from bench_harness import container_entrypoint
from bench_harness.runpod_runtime import CloudRuntimeConfig


MODEL_ENTRYPOINTS = (
    ("3dtopia-xl", "python", "/opt/3dgen-runner/3dtopia_xl_runner.py"),
    ("direct3d-s2", "python3", "/opt/3dgen-runner/direct3d_s2_runner.py"),
    ("hunyuan3d-21", "python3", "/opt/3dgen-runner/hunyuan3d_21_runner.py"),
    ("partcrafter", "python3", "/opt/3dgen-runner/partcrafter_runner.py"),
    ("pixal3d", "python3", "/opt/3dgen-runner/pixal3d_runner.py"),
    ("sf3d", "python3", "/opt/3dgen-runner/sf3d_runner.py"),
    ("step1x-3d", "python3", "/opt/3dgen-runner/step1x_3d_runner.py"),
    ("trellis1", "python3", "/opt/3dgen-runner/trellis1_runner.py"),
    ("trellis2", "python3", "/opt/3dgen-runner/trellis2_runner.py"),
    ("triposg", "python3", "/opt/3dgen-runner/triposg_runner.py"),
    ("triposr", "python3", "/opt/3dgen-runner/triposr_runner.py"),
)
REPO_ROOT = Path(__file__).resolve().parents[2]


class RunnerExecCalled(Exception):
    pass


def test_runner_mode_execs_baked_runner_with_current_python(monkeypatch, tmp_path: Path) -> None:
    runner_path = tmp_path / "model_runner.py"
    runner_path.write_text("raise AssertionError('exec should replace the entrypoint')\n", encoding="utf-8")
    captured = {}

    def fake_execv(executable: str, command: list[str]) -> None:
        captured["executable"] = executable
        captured["command"] = command
        raise RunnerExecCalled

    monkeypatch.setattr(container_entrypoint.os, "execv", fake_execv)

    with pytest.raises(RunnerExecCalled):
        container_entrypoint.main(
            [
                "--model-id",
                "triposr",
                "--runner-path",
                str(runner_path),
                "runner",
                "--task-limit",
                "2",
            ]
        )

    assert captured == {
        "executable": sys.executable,
        "command": [sys.executable, str(runner_path), "--task-limit", "2"],
    }


def test_runpod_mode_builds_runtime_config_from_baked_runner(monkeypatch, tmp_path: Path) -> None:
    runner_path = tmp_path / "model_runner.py"
    runner_path.write_text("pass\n", encoding="utf-8")
    captured: list[CloudRuntimeConfig] = []

    def fake_run_cloud_runtime(config: CloudRuntimeConfig) -> int:
        captured.append(config)
        return 17

    monkeypatch.setattr(container_entrypoint, "run_cloud_runtime", fake_run_cloud_runtime)

    with pytest.raises(SystemExit) as exc_info:
        container_entrypoint.main(
            [
                "--model-id",
                "triposg",
                "--runner-path",
                str(runner_path),
                "runpod",
                "--output-root",
                str(tmp_path / "output"),
                "--s3-target",
                "s3://bucket/runs/triposg/test",
                "--",
                "--task-limit",
                "2",
            ]
        )

    assert exc_info.value.code == 17
    assert captured == [
        CloudRuntimeConfig(
            model_id="triposg",
            output_root=tmp_path / "output",
            s3_target="s3://bucket/runs/triposg/test",
            runner_command=(sys.executable, str(runner_path), "--task-limit", "2"),
        )
    ]


def test_missing_mode_fails_fast(tmp_path: Path, capsys) -> None:
    runner_path = tmp_path / "model_runner.py"
    runner_path.write_text("pass\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        container_entrypoint.main(
            ["--model-id", "triposr", "--runner-path", str(runner_path)]
        )

    assert exc_info.value.code == 2
    assert "the following arguments are required: mode" in capsys.readouterr().err


def test_runpod_mode_requires_runner_argument_separator(tmp_path: Path, capsys) -> None:
    runner_path = tmp_path / "model_runner.py"
    runner_path.write_text("pass\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        container_entrypoint.main(
            [
                "--model-id",
                "triposr",
                "--runner-path",
                str(runner_path),
                "runpod",
                "--output-root",
                str(tmp_path / "output"),
                "--s3-target",
                "s3://bucket/run",
            ]
        )

    assert exc_info.value.code == 2
    assert "runner arguments must follow --" in capsys.readouterr().err


@pytest.mark.parametrize(("model_id", "python_command", "runner_path"), MODEL_ENTRYPOINTS)
def test_model_dockerfile_bakes_single_explicit_container_entrypoint(
    model_id: str,
    python_command: str,
    runner_path: str,
) -> None:
    dockerfile = (REPO_ROOT / "models" / model_id / "Dockerfile").read_text(encoding="utf-8")
    expected_entrypoint = (
        f'ENTRYPOINT ["{python_command}", "-m", "bench_harness.container_entrypoint", '
        f'"--model-id", "{model_id}", "--runner-path", "{runner_path}"]'
    )

    assert dockerfile.count("ENTRYPOINT [") == 1
    assert expected_entrypoint in dockerfile
    assert "COPY bench/src /opt/bench/src" in dockerfile
    assert "PYTHONPATH=/opt/bench/src" in dockerfile
    assert "\nCMD " not in dockerfile


def test_runpod_entrypoint_dependencies_are_explicit() -> None:
    topia = (REPO_ROOT / "models" / "3dtopia-xl" / "Dockerfile").read_text(encoding="utf-8")
    triposr = (REPO_ROOT / "models" / "triposr" / "Dockerfile").read_text(encoding="utf-8")
    step1x = (REPO_ROOT / "models" / "step1x-3d" / "Dockerfile").read_text(encoding="utf-8")

    assert "boto3==1.42.97" in topia
    assert "openssh-server" in triposr
    assert "uv pip install --system boto3" in step1x


@pytest.mark.parametrize("model_id", ("triposr", "triposg", "partcrafter"))
def test_local_smoke_docs_select_runner_mode(model_id: str) -> None:
    readme = (REPO_ROOT / "models" / model_id / "README.md").read_text(encoding="utf-8")

    assert f"3dgen/{model_id}:local runner --task-limit 2" in readme
