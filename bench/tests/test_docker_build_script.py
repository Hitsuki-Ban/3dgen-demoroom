from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT_PATH = REPO_ROOT / "scripts" / "docker-build-model.ps1"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"


def test_docker_build_wrapper_uses_repo_root_context_for_cloud_assets() -> None:
    script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "$dockerArgs += \".\"" in script
    assert 'Join-Path "models\\$Model" "Dockerfile"' in script
    assert '"type=local,dest=$newCacheRoot,mode=max"' in script
    assert "[switch] $Push" in script
    assert 'throw "Use either -Load or -Push, not both."' in script
    assert '$dockerArgs += "--push"' in script
    assert "if (-not $Load -and -not $Push)" in script


def test_docker_build_wrapper_accepts_wave2_models() -> None:
    script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    for model_id in (
        "trellis1",
        "3dtopia-xl",
        "trellis2",
        "direct3d-s2",
        "step1x-3d",
        "pixal3d",
        "hunyuan3d-21",
        "sf3d",
    ):
        assert f'"{model_id}"' in script


def test_root_dockerignore_excludes_generated_large_paths() -> None:
    dockerignore = DOCKERIGNORE_PATH.read_text(encoding="utf-8")

    assert ".git" in dockerignore
    assert ".worktrees" in dockerignore
    assert ".docker-build" in dockerignore
    assert ".docker-data" in dockerignore
    assert "outputs" in dockerignore
    assert "bench/.venv" in dockerignore
