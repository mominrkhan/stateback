"""Bind SB-011 G10 evidence to the exact tagged release overlay."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path

CHECKPOINT_PATH = Path("outputs/SB-011-phase18-checkpoint.md")
MANIFEST_PATH = Path("outputs/SB-011-phase18-manifest.sha256")
ACCEPTANCE_PATH = Path("outputs/SB-011-final-acceptance.md")

_SOURCE_BASE = re.compile(r"\*\*Source base:\*\* `([0-9a-f]{40})`")
_CHECKPOINT_MANIFEST = re.compile(
    r"manifest's aggregate SHA-256 is\s+`([0-9a-f]{64})`", re.MULTILINE
)
_ACCEPTANCE_SOURCE_BASE = re.compile(r"\*\*Reviewed source base:\*\* `([0-9a-f]{40})`")
_ACCEPTANCE_MANIFEST = re.compile(
    r"\*\*Reviewed manifest SHA-256:\*\* `([0-9a-f]{64})`"
)
_G10_PASS = re.compile(r"^G10: PASS \(full\)$", re.MULTILINE)
_MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^\0\r\n]+)")


class ReleaseEvidenceError(RuntimeError):
    """Release evidence does not describe the candidate revision."""


def _required_match(pattern: re.Pattern[str], text: str, label: str) -> str:
    match = pattern.search(text)
    if match is None:
        raise ReleaseEvidenceError(f"missing {label}")
    return match.group(1)


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseEvidenceError(detail or "git evidence check failed") from exc


def verify_release_evidence(root: Path, *, revision: str = "HEAD") -> str:
    """Verify checksums and the exact source-base-to-revision reviewed overlay."""

    root = root.resolve()
    checkpoint = (root / CHECKPOINT_PATH).read_text(encoding="utf-8")
    acceptance = (root / ACCEPTANCE_PATH).read_text(encoding="utf-8")
    manifest_bytes = (root / MANIFEST_PATH).read_bytes()
    source_base = _required_match(_SOURCE_BASE, checkpoint, "checkpoint source base")
    checkpoint_digest = _required_match(
        _CHECKPOINT_MANIFEST, checkpoint, "checkpoint manifest digest"
    )
    acceptance_base = _required_match(
        _ACCEPTANCE_SOURCE_BASE, acceptance, "acceptance source base"
    )
    acceptance_digest = _required_match(
        _ACCEPTANCE_MANIFEST, acceptance, "acceptance manifest digest"
    )
    if _G10_PASS.search(acceptance) is None:
        raise ReleaseEvidenceError("missing exact G10-full PASS verdict")
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if not (
        source_base == acceptance_base
        and actual_digest == checkpoint_digest == acceptance_digest
    ):
        raise ReleaseEvidenceError("review evidence binding mismatch")

    manifest_paths: set[str] = set()
    for line_number, line in enumerate(
        manifest_bytes.decode("utf-8").splitlines(), start=1
    ):
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise ReleaseEvidenceError(f"invalid manifest line {line_number}")
        expected_digest, relative = match.groups()
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or relative in manifest_paths:
            raise ReleaseEvidenceError(f"unsafe or duplicate manifest path: {relative}")
        candidate = root / path
        if not candidate.is_file():
            raise ReleaseEvidenceError(f"manifest path is not a file: {relative}")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_digest:
            raise ReleaseEvidenceError(f"manifest checksum mismatch: {relative}")
        manifest_paths.add(relative)

    _git(root, "merge-base", "--is-ancestor", source_base, revision)
    changed = {
        path.decode("utf-8")
        for path in _git(
            root, "diff", "--no-renames", "--name-only", "-z", source_base, revision
        ).split(b"\0")
        if path
    }
    expected = manifest_paths | {
        CHECKPOINT_PATH.as_posix(),
        MANIFEST_PATH.as_posix(),
        ACCEPTANCE_PATH.as_posix(),
    }
    if changed != expected:
        missing = sorted(expected - changed)
        unreviewed = sorted(changed - expected)
        raise ReleaseEvidenceError(
            f"reviewed overlay mismatch; missing={missing!r}; unreviewed={unreviewed!r}"
        )
    return actual_digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    try:
        digest = verify_release_evidence(args.root, revision=args.revision)
    except (OSError, UnicodeError, ReleaseEvidenceError) as exc:
        parser.exit(1, f"release evidence verification failed: {exc}\n")
    print(f"release evidence verified: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
