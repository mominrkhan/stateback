from __future__ import annotations

import pytest

from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.secrets import reject_secrets_in_json

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "payload",
    [
        {"authorization": "Bearer abc"},
        {"access_token": "x"},
        {"password": "x"},
        {"private_key": "x"},
        {"note": "-----BEGIN PRIVATE KEY-----"},
    ],
)
def test_secret_payloads_rejected(payload: dict[str, str]) -> None:
    with pytest.raises(ContractValidationError) as exc:
        reject_secrets_in_json(json_from_plain(payload), field="test")
    assert exc.value.reason_code == "secret_field"
