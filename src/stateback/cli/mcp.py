"""Installed stdio MCP command using only Stateback API credentials."""

from __future__ import annotations

import json
import os
from pathlib import Path

from stateback.mcp import create_api_mcp_server
from stateback.sdk import StatebackClient
from stateback.sdk.facade import LocalConfigurationError, _local_connection


def print_mcp_config() -> None:
    print(json.dumps({"command": "stateback", "args": ["mcp"]}, indent=2))


def run_mcp(*, print_config: bool = False, start: Path | None = None) -> None:
    if print_config:
        print_mcp_config()
        return
    base_url = os.environ.get("STATEBACK_API_URL")
    token = os.environ.get("STATEBACK_API_TOKEN")
    if bool(base_url) != bool(token):
        raise LocalConfigurationError(
            "STATEBACK_API_URL and STATEBACK_API_TOKEN must be supplied together"
        )
    if base_url is None or token is None:
        base_url, token = _local_connection(start)
    client = StatebackClient(base_url=base_url, token=token)
    try:
        create_api_mcp_server(client).run("stdio")
    finally:
        client.close()
