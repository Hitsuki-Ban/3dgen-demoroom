from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


REQUIRED_R2_ENV_VARS = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


def validate_relative_upload_name(relative_name: str) -> Path:
    relative_path = Path(relative_name)
    if relative_path == Path("."):
        return Path("")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("upload target must be a relative path under the uploader root")
    return relative_path


@dataclass(frozen=True)
class LocalUploader:
    root: Path

    def upload_run(self, source_dir: Path, relative_name: str) -> Path:
        if not source_dir.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {source_dir}")
        relative_path = validate_relative_upload_name(relative_name)

        destination = self.root / relative_path
        if destination.exists():
            raise FileExistsError(f"upload destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, destination)
        return destination


@dataclass(frozen=True)
class S3UploadConfig:
    bucket: str
    prefix: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_target(cls, target: str, env: Mapping[str, str]) -> S3UploadConfig:
        parsed = urlparse(target)
        if parsed.scheme != "s3" or not parsed.netloc:
            raise ValueError("S3 upload target must use s3://<bucket>/<prefix>")
        missing = [name for name in REQUIRED_R2_ENV_VARS if not env.get(name)]
        if missing:
            raise ValueError(f"missing required R2 environment variable(s): {', '.join(missing)}")
        return cls(
            bucket=parsed.netloc,
            prefix=parsed.path.strip("/"),
            endpoint_url=env["R2_ENDPOINT"],
            access_key_id=env["R2_ACCESS_KEY_ID"],
            secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        )


@dataclass(frozen=True)
class S3Uploader:
    config: S3UploadConfig
    client: Any | None = None

    def upload_run(self, source_dir: Path, relative_name: str = "") -> list[str]:
        if not source_dir.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {source_dir}")
        relative_path = validate_relative_upload_name(relative_name)
        client = self.client if self.client is not None else create_s3_client(self.config)
        uploaded_keys: list[str] = []
        for source_file in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            key_parts = [
                part
                for part in (
                    self.config.prefix,
                    relative_path.as_posix() if relative_path.parts else "",
                    source_file.relative_to(source_dir).as_posix(),
                )
                if part
            ]
            key = "/".join(key_parts)
            client.upload_file(str(source_file), self.config.bucket, key)
            uploaded_keys.append(key)
        return uploaded_keys


def create_s3_client(config: S3UploadConfig) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for S3/R2 uploads") from exc
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
    )


def create_uploader(
    kind: str,
    target: str,
    *,
    env: Mapping[str, str] | None = None,
    s3_client: Any | None = None,
) -> LocalUploader | S3Uploader:
    if kind == "local":
        return LocalUploader(Path(target))
    if kind == "s3":
        return S3Uploader(S3UploadConfig.from_target(target, os.environ if env is None else env), client=s3_client)
    raise ValueError(f"unknown uploader kind: {kind}")
