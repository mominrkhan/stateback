"""GitHub REST provider integration."""

from stateback.providers.github.adapter import GitHubAdapter
from stateback.providers.github.effects import (
    EFFECT_ADD_LABEL,
    EFFECT_CREATE_ISSUE,
    EFFECT_CREATE_ISSUE_COMMENT,
    EFFECT_CREATE_PULL_REQUEST,
    EFFECT_MERGE_PULL_REQUEST,
    GITHUB_EFFECTS,
    GITHUB_PROVIDER,
)
from stateback.providers.github.transport import GitHubHttpResponse, GitHubTransport

__all__ = [
    "EFFECT_ADD_LABEL",
    "EFFECT_CREATE_ISSUE",
    "EFFECT_CREATE_ISSUE_COMMENT",
    "EFFECT_CREATE_PULL_REQUEST",
    "EFFECT_MERGE_PULL_REQUEST",
    "GITHUB_EFFECTS",
    "GITHUB_PROVIDER",
    "GitHubAdapter",
    "GitHubHttpResponse",
    "GitHubTransport",
]
