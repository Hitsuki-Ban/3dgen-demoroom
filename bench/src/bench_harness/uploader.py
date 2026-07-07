from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalUploader:
    root: Path

    def upload_run(self, source_dir: Path, relative_name: str) -> Path:
        if not source_dir.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {source_dir}")
        relative_path = Path(relative_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("upload target must be a relative path under the uploader root")

        destination = self.root / relative_path
        if destination.exists():
            raise FileExistsError(f"upload destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, destination)
        return destination


def create_uploader(kind: str, target: str) -> LocalUploader:
    if kind == "local":
        return LocalUploader(Path(target))
    if kind == "s3":
        raise NotImplementedError("S3 uploader is not implemented in the local-first harness PR")
    raise ValueError(f"unknown uploader kind: {kind}")
