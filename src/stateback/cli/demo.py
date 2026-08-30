"""Explicit local UNKNOWN demonstration through the real runtime path."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from stateback.application.ids import request_identity, submit_ids
from stateback.cli.config import load_project_config
from stateback.cli.project import create_file, find_project_root
from stateback.sdk import StatebackClient, StatebackClientError, StatebackTransportError
from stateback.sdk.facade import LocalConfigurationError, _local_caller


class DemoError(RuntimeError):
    """The local UNKNOWN demonstration cannot proceed safely."""


def run_unknown_demo(
    *,
    owner: str,
    repo: str,
    confirm_mutation: bool,
    timeout: float = 180.0,
    start: Path | None = None,
) -> None:
    root = find_project_root(start or Path.cwd())
    config = load_project_config(root / "stateback.toml")
    if not config.github_enabled:
        raise DemoError(
            "GitHub is not connected. Run `stateback connect github` first."
        )
    if not owner.strip() or not repo.strip() or "/" in owner or "/" in repo:
        raise DemoError("--owner and --repo must identify one GitHub repository")
    arm_directory = root / ".stateback" / "run" / "demo-unknown"
    if arm_directory.is_symlink() or not arm_directory.is_dir():
        raise DemoError(
            "The local demo worker is unavailable. Start `stateback dev` first."
        )
    if not (arm_directory.parent / "worker.ready").is_file():
        raise DemoError(
            "The local demo worker is not ready. Start `stateback dev` first."
        )
    if not confirm_mutation:
        print(
            "This demo will create one real issue in:\n"
            f"  {owner}/{repo}\n\n"
            "It will intentionally simulate a lost provider response after GitHub "
            "accepts the mutation.\n"
        )
        try:
            answer = input("Continue? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in {"y", "yes"}:
            print("Demo cancelled.")
            return

    base_url, token, principal = _local_caller(root)
    key = f"stateback-unknown-demo-{secrets.token_hex(12)}"
    expected_id = submit_ids(request_identity(principal, key)).operation_id
    arm_file = arm_directory / expected_id.value
    if not create_file(arm_file, b"armed\n", mode=0o600):
        raise DemoError("the exact demo operation is already armed")

    client = StatebackClient(base_url=base_url, token=token)
    saw_unknown = False
    told_approval = False
    preserve_arm = False
    try:
        handle = client.submit(
            effect={"provider": "github", "action": "create_issue", "version": "v1"},
            arguments={
                "owner": owner,
                "repo": repo,
                "title": f"Stateback UNKNOWN demo {expected_id.value[:8]}",
                "body": (
                    "This sandbox issue demonstrates recovery after a provider "
                    "success response is lost."
                ),
            },
            idempotency_key=key,
            deployment_environment="local-development",
        )
        if handle.operation_id != expected_id.value:
            raise DemoError("Stateback returned an unexpected operation identity")
        print(f"✓ Operation submitted\n  {handle.operation_id}")
        deadline = time.monotonic() + timeout
        status = handle.status()
        while time.monotonic() < deadline:
            saw_unknown = saw_unknown or status.state in {"UNKNOWN", "VERIFYING"}
            if status.state == "AWAITING_APPROVAL" and not told_approval:
                print("\nApprove the demo operation in the Stateback Operator UI.")
                told_approval = True
            if status.is_forward_terminal or status.state == "MANUAL_INTERVENTION":
                break
            time.sleep(0.25)
            status = handle.status()
        audit = handle.audit(limit=100)
        serialized_audit = json.dumps(audit, sort_keys=True)
        lost_response_recorded = "github.demo.response_lost" in serialized_audit
        verification_applied = (
            "verification.completed.v1" in serialized_audit
            and '"APPLIED"' in serialized_audit
        )
        if (
            status.state == "SUCCEEDED"
            and lost_response_recorded
            and verification_applied
        ):
            print(
                "\n? Provider outcome became uncertain\n"
                "  Stateback did not blindly retry.\n\n"
                "✓ Existing marked GitHub issue found\n"
                "✓ Operation reconciled to Succeeded\n\n"
                "The demo issue remains visible in the sandbox repository."
            )
        else:
            uncertainty = " after entering UNKNOWN" if saw_unknown else ""
            print(
                f"\nOperation remains {status.state}{uncertainty}. Stateback has not "
                "forced a successful conclusion."
            )
        print(f"\nOperator UI:\n  {base_url}/operations/{handle.operation_id}")
    except StatebackTransportError as exc:
        # Submission or observation may have crossed the API boundary. Keeping the
        # operation-scoped marker is safer than silently disabling the promised
        # fault for an operation that may already be durable.
        preserve_arm = True
        raise DemoError(
            "The local Stateback API response was unavailable; no durable conclusion "
            f"can be inferred. Inspect operation {expected_id.value}. This command did "
            "not remove an unconsumed demo arm; the worker may already have consumed "
            f"it. Arm path: {arm_file}."
        ) from exc
    except StatebackClientError as exc:
        raise DemoError(
            f"Stateback rejected the demo request ({exc.code}); no provider success "
            "is inferred"
        ) from exc
    except LocalConfigurationError as exc:
        raise DemoError(
            "The local Stateback API is unavailable; no durable conclusion can be inferred"
        ) from exc
    finally:
        if not preserve_arm:
            arm_file.unlink(missing_ok=True)
        client.close()
