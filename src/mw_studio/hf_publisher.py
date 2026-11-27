"""HuggingFace dataset/artifact publisher for mw-studio with CAN-0011 & SHA-256 manifest enforcement."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable
from urllib import request as urllib_request

from mw_studio.poster import validate_can_0011

DEFAULT_HF_API_BASE = "https://huggingface.co/api"


@dataclass(frozen=True)
class HfArtifactFile:
    path_in_repo: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class HfPublishReceipt:
    repo_id: str
    repo_type: str
    revision: str
    commit_url: str
    manifest_sha256: str
    file_count: int
    dry_run: bool


def prepare_hf_artifact(path_in_repo: str, content: bytes | str) -> HfArtifactFile:
    cleaned_path = path_in_repo.strip().lstrip("/")
    if not cleaned_path or ".." in cleaned_path.split("/"):
        raise ValueError(f"Invalid path_in_repo: {path_in_repo!r}")
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    if isinstance(content, str):
        validate_can_0011({"content": content, "path": cleaned_path})
    digest = hashlib.sha256(raw).hexdigest()
    return HfArtifactFile(path_in_repo=cleaned_path, content=raw, sha256=digest)


def publish_to_huggingface(
    repo_id: str,
    files: list[HfArtifactFile | dict[str, Any]],
    *,
    token: str | None = None,
    repo_type: str = "dataset",
    revision: str = "main",
    commit_message: str = "Publish MoonWitness studio artifact bundle",
    api_base: str = DEFAULT_HF_API_BASE,
    dry_run: bool = False,
    transport: Callable[[str, dict[str, str], bytes], dict[str, Any]] | None = None,
) -> HfPublishReceipt:
    """Publish verified studio artifacts to HuggingFace Hub (or dry-run/injected transport)."""
    cleaned_repo = repo_id.strip()
    if not cleaned_repo or "/" not in cleaned_repo:
        raise ValueError("repo_id must be in '<namespace>/<name>' format")
    if repo_type not in ("dataset", "model", "space"):
        raise ValueError("repo_type must be one of: dataset, model, space")
    if not files:
        raise ValueError("files list must not be empty")

    validate_can_0011({"repo_id": cleaned_repo, "commit_message": commit_message})

    normalized_files: list[HfArtifactFile] = []
    for entry in files:
        if isinstance(entry, HfArtifactFile):
            normalized_files.append(entry)
        elif isinstance(entry, dict):
            normalized_files.append(
                prepare_hf_artifact(
                    str(entry.get("path_in_repo", "")),
                    entry.get("content", b""),
                )
            )
        else:
            raise ValueError("Unsupported file entry type")

    manifest_entries = [
        {"path": item.path_in_repo, "sha256": item.sha256, "size": len(item.content)}
        for item in sorted(normalized_files, key=lambda f: f.path_in_repo)
    ]
    manifest_json = json.dumps(
        {
            "repo_id": cleaned_repo,
            "repo_type": repo_type,
            "revision": revision,
            "can_0011": "enforced",
            "files": manifest_entries,
        },
        sort_keys=True,
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_json).hexdigest()

    if dry_run:
        return HfPublishReceipt(
            repo_id=cleaned_repo,
            repo_type=repo_type,
            revision=revision,
            commit_url=f"https://huggingface.co/{repo_type}s/{cleaned_repo}/commit/dry-run-{manifest_sha256[:12]}",
            manifest_sha256=manifest_sha256,
            file_count=len(normalized_files),
            dry_run=True,
        )

    if not token or not token.strip():
        raise ValueError("HuggingFace token is required when dry_run=False")

    endpoint = f"{api_base.rstrip('/')}/{repo_type}s/{cleaned_repo}/commit/{revision}"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload_bytes = json.dumps(
        {
            "summary": commit_message,
            "manifest_sha256": manifest_sha256,
            "files": manifest_entries,
        }
    ).encode("utf-8")

    if transport is not None:
        response_data = transport(endpoint, headers, payload_bytes)
    else:
        req = urllib_request.Request(endpoint, data=payload_bytes, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=15) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))

    commit_url = str(
        response_data.get(
            "commitUrl",
            f"https://huggingface.co/{repo_type}s/{cleaned_repo}/commit/{manifest_sha256[:12]}",
        )
    )
    return HfPublishReceipt(
        repo_id=cleaned_repo,
        repo_type=repo_type,
        revision=revision,
        commit_url=commit_url,
        manifest_sha256=manifest_sha256,
        file_count=len(normalized_files),
        dry_run=False,
    )
