from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT_PATH = REPO_ROOT / "scripts" / "docker-build-model.ps1"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"


def test_docker_build_wrapper_uses_repo_root_context_for_cloud_assets() -> None:
    script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "$dockerArgs += \".\"" in script
    assert 'Join-Path "models\\$Model" "Dockerfile"' in script
    assert '"type=local,dest=$newCacheRoot,mode=max"' in script


def test_root_dockerignore_excludes_generated_large_paths() -> None:
    dockerignore = DOCKERIGNORE_PATH.read_text(encoding="utf-8")

    assert ".git" in dockerignore
    assert ".worktrees" in dockerignore
    assert ".docker-build" in dockerignore
    assert "outputs" in dockerignore
    assert "bench/.venv" in dockerignore
