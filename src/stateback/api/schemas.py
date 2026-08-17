"""Strict public v1 request schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EffectSchema(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)


class SubmitOperationSchema(StrictModel):
    contract_version: Literal["v1"]
    effect: EffectSchema
    arguments: Any
    metadata: dict[str, str] = Field(default_factory=dict)
    deployment_environment: str = Field(min_length=1, max_length=100)


class ApprovalActionSchema(StrictModel):
    contract_version: Literal["v1"]
    approval_id: str
    expected_version: int = Field(ge=1)
    decision: Literal["APPROVED", "REJECTED"]
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class OperatorActionSchema(StrictModel):
    contract_version: Literal["v1"]
    expected_version: int = Field(ge=1)
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
