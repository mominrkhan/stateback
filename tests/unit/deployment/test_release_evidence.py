from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from stateback.deployment.release_evidence import (
    ACCEPTANCE_PATH,
    CHECKPOINT_PATH,
    MANIFEST_PATH,
    ReleaseEvidenceError,
    verify_release_evidence,
)

pytestmark = pytest.mark.unit


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _candidate(tmp_path: Path, *, rename_base: bool = False) -> tuple[Path, str]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Stateback Test")
    _git(tmp_path, "config", "user.email", "stateback@example.invalid")
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-qm", "base")
    source_base = _git(tmp_path, "rev-parse", "HEAD")

    payload = tmp_path / "payload.txt"
    if rename_base:
        (tmp_path / "base.txt").rename(payload)
    else:
        payload.write_text("reviewed\n", encoding="utf-8")
    for path in (CHECKPOINT_PATH, MANIFEST_PATH, ACCEPTANCE_PATH):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    payload_digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest = f"{payload_digest}  payload.txt\n"
    (tmp_path / MANIFEST_PATH).write_text(manifest, encoding="utf-8")
    manifest_digest = hashlib.sha256(manifest.encode()).hexdigest()
    (tmp_path / CHECKPOINT_PATH).write_text(
        f"**Source base:** `{source_base}`\n\n"
        f"manifest's aggregate SHA-256 is\n`{manifest_digest}`.\n",
        encoding="utf-8",
    )
    (tmp_path / ACCEPTANCE_PATH).write_text(
        "G10: PASS (full)\n\n"
        f"**Reviewed source base:** `{source_base}`\n\n"
        f"**Reviewed manifest SHA-256:** `{manifest_digest}`\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "candidate")
    return tmp_path, manifest_digest


def test_release_evidence_binds_complete_overlay(tmp_path: Path) -> None:
    root, digest = _candidate(tmp_path)
    assert verify_release_evidence(root) == digest


def test_stale_review_cannot_authorize_changed_release_tree(tmp_path: Path) -> None:
    root, _ = _candidate(tmp_path)
    (root / "payload.txt").write_text("changed after review\n", encoding="utf-8")
    _git(root, "add", "payload.txt")
    _git(root, "commit", "-qm", "unreviewed change")

    with pytest.raises(ReleaseEvidenceError, match="checksum mismatch"):
        verify_release_evidence(root)


def test_stale_review_cannot_authorize_unreviewed_added_file(tmp_path: Path) -> None:
    root, _ = _candidate(tmp_path)
    (root / "unreviewed.py").write_text("print('drift')\n", encoding="utf-8")
    _git(root, "add", "unreviewed.py")
    _git(root, "commit", "-qm", "unreviewed file")

    with pytest.raises(ReleaseEvidenceError, match="unreviewed.py"):
        verify_release_evidence(root)


def test_rename_cannot_hide_deletion_from_reviewed_overlay(tmp_path: Path) -> None:
    root, _ = _candidate(tmp_path, rename_base=True)

    with pytest.raises(ReleaseEvidenceError, match="base.txt"):
        verify_release_evidence(root)


def test_deletion_cannot_reuse_stale_review(tmp_path: Path) -> None:
    root, _ = _candidate(tmp_path)
    (root / "base.txt").unlink()
    _git(root, "add", "base.txt")
    _git(root, "commit", "-qm", "unreviewed deletion")

    with pytest.raises(ReleaseEvidenceError, match="base.txt"):
        verify_release_evidence(root)
