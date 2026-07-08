from pathlib import Path

from bench_harness import cli
from bench_harness.runpod import RunPodLaunchConfig


class FakeUploader:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str]] = []

    def upload_run(self, source_dir: Path, relative_name: str = "") -> list[str]:
        self.calls.append((source_dir, relative_name))
        return ["runs/triposg/task/output.glb", "runs/triposg/task/meta.json"]


def test_upload_s3_command_uses_s3_uploader(monkeypatch, tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    source.mkdir()
    fake_uploader = FakeUploader()

    def fake_create_uploader(kind: str, target: str):
        assert kind == "s3"
        assert target == "s3://3dgen-runs/runs/triposg"
        return fake_uploader

    monkeypatch.setattr(cli, "create_uploader", fake_create_uploader)
    monkeypatch.setattr(
        "sys.argv",
        ["bench-harness", "upload-s3", str(source), "s3://3dgen-runs/runs/triposg"],
    )

    cli.main()

    assert fake_uploader.calls == [(source, "")]
    assert capsys.readouterr().out == "uploaded objects: 2\n"


def test_runpod_launch_command_uses_env_credentials_and_issue_defaults(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeRunPodClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

        def launch_pod(self, config: RunPodLaunchConfig, min_balance_usd: float) -> dict[str, object]:
            captured["config"] = config
            captured["min_balance_usd"] = min_balance_usd
            return {"id": "pod-123", "desiredStatus": "RUNNING"}

    monkeypatch.setattr(cli, "RunPodClient", FakeRunPodClient)
    monkeypatch.setenv("RUNPOD_API_KEY", "token")
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setattr(
        "sys.argv",
        [
            "bench-harness",
            "runpod-launch",
            "triposg",
            "ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
            "s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
            "--name",
            "3dgen-triposg-wave1",
            "--container-registry-auth-id",
            "cmrc1l2gc00847uotrnjn2des",
            "--network-volume-id",
            "volume-123",
            "--startup-timeout-min",
            "20",
            "--data-center-id",
            "US-IL-1",
        ],
    )

    cli.main()

    config = captured["config"]
    assert isinstance(config, RunPodLaunchConfig)
    assert captured["api_key"] == "token"
    assert captured["min_balance_usd"] == 5.0
    assert config.max_runtime_min == 90
    assert config.gpu_type_ids == ("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090")
    assert config.allowed_cuda_versions == ("12.8",)
    assert config.container_registry_auth_id == "cmrc1l2gc00847uotrnjn2des"
    assert config.network_volume_id == "volume-123"
    assert config.data_center_id == "US-IL-1"
    assert config.startup_timeout_min == 20
    assert config.r2_credentials.endpoint == "https://example.r2.cloudflarestorage.com"
    assert capsys.readouterr().out == '{"desiredStatus": "RUNNING", "id": "pod-123"}\n'


def test_runpod_pods_command_lists_pods(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeRunPodClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

        def list_pods(self) -> dict[str, object]:
            return {"pods": []}

    monkeypatch.setattr(cli, "RunPodClient", FakeRunPodClient)
    monkeypatch.setenv("RUNPOD_API_KEY", "token")
    monkeypatch.setattr("sys.argv", ["bench-harness", "runpod-pods"])

    cli.main()

    assert captured["api_key"] == "token"
    assert capsys.readouterr().out == '{"pods": []}\n'


def test_runpod_terminate_command_deletes_pod(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeRunPodClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

        def terminate_pod(self, pod_id: str) -> dict[str, object]:
            captured["pod_id"] = pod_id
            return {"deleted": True, "id": pod_id}

    monkeypatch.setattr(cli, "RunPodClient", FakeRunPodClient)
    monkeypatch.setenv("RUNPOD_API_KEY", "token")
    monkeypatch.setattr("sys.argv", ["bench-harness", "runpod-terminate", "pod-123"])

    cli.main()

    assert captured == {"api_key": "token", "pod_id": "pod-123"}
    assert capsys.readouterr().out == '{"deleted": true, "id": "pod-123"}\n'
