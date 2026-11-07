"""Model artifacts: Vultr Object Storage (S3-compatible) when S3_* is set, else a local directory.

Artifact keys are `s3:<key>` or `local:<path relative to MODEL_ROOT>`. boto3 is imported lazily
so services without Object Storage don't need it."""

from __future__ import annotations

import os
from pathlib import Path


def s3_enabled() -> bool:
    return all(os.environ.get(k) for k in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET"))


def _client():
    import boto3

    return boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                        aws_secret_access_key=os.environ["S3_SECRET_KEY"])


def model_root() -> Path:
    return Path(os.environ.get("MODEL_ROOT", "."))


def presign(key: str, method: str = "put_object", ttl_s: int = 3600) -> str:
    return _client().generate_presigned_url(method, Params={"Bucket": os.environ["S3_BUCKET"], "Key": key},
                                            ExpiresIn=ttl_s)


def fetch(artifact_key: str, cache_dir: Path | None = None) -> Path:
    """Local path of an artifact, downloading from Object Storage into the cache when needed."""
    kind, _, ref = artifact_key.partition(":")
    if kind == "local":
        return model_root() / ref
    if kind == "s3":
        dest = (cache_dir or Path(os.environ.get("MODEL_CACHE", "/tmp/zentry-models"))) / ref.replace("/", "_")
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            _client().download_file(os.environ["S3_BUCKET"], ref, str(dest))
        return dest
    raise ValueError(f"unsupported artifact {artifact_key}")
