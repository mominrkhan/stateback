"""HTTP v1 transport. Route code never calls repositories or providers."""

from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from stateback.api.schemas import (
    ApprovalActionSchema,
    OperatorActionSchema,
    SemanticSummaryRequestSchema,
    SubmitOperationSchema,
)
from stateback.application.auth import (
    AuthenticatedIdentity,
    AuthenticationError,
    AuthenticationUnavailableError,
    Authenticator,
    AuthorizationError,
)
from stateback.application.input_validation import bounded_json_from_plain
from stateback.application.models import OperationSearch, SubmitOperationRequest
from stateback.application.service import ApplicationService, ApplicationServiceError
from stateback.domain.enums import ApprovalState
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import EffectRef
from stateback.persistence.exceptions import PersistenceError


def _credential(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    if len(authorization) > 4096:
        raise AuthenticationError("invalid_authorization_header")
    scheme, separator, value = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not value:
        raise AuthenticationError("invalid_authorization_header")
    return value


def _status_for(code: str, retryable: bool) -> int:
    if code == "not_found":
        return 404
    if code in {
        "idempotency_conflict",
        "concurrency_conflict",
        "stale_version",
        "source_state_mismatch",
        "approval_state_conflict",
    }:
        return 409
    if retryable or code.endswith("_unavailable") or code.startswith("persist_failed"):
        return 503
    return 422


def _error(code: str, status: int, *, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "contract_version": "v1",
            "error": {
                "code": code,
                "message": code.replace("_", " "),
                "retryable": retryable,
                "correlation_id": None,
            },
        },
    )


def create_app(*, service: ApplicationService, authenticator: Authenticator) -> FastAPI:
    app = FastAPI(title="Stateback", version="v1")

    def authenticate(
        authorization: Annotated[str | None, Header()] = None,
    ) -> AuthenticatedIdentity:
        try:
            return authenticator.authenticate(_credential(authorization))
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationUnavailableError("authentication_unavailable") from exc

    Identity = Annotated[AuthenticatedIdentity, Depends(authenticate)]

    @app.exception_handler(AuthenticationError)
    def authentication_error(
        _request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        return _error(str(exc), 401)

    @app.exception_handler(AuthorizationError)
    def authorization_error(_request: Request, exc: AuthorizationError) -> JSONResponse:
        return _error(str(exc), 403)

    @app.exception_handler(AuthenticationUnavailableError)
    def authentication_unavailable_error(
        _request: Request, exc: AuthenticationUnavailableError
    ) -> JSONResponse:
        return _error(str(exc), 503, retryable=True)

    @app.exception_handler(ApplicationServiceError)
    def application_error(
        _request: Request, exc: ApplicationServiceError
    ) -> JSONResponse:
        return _error(
            exc.code,
            _status_for(exc.code, exc.retryable),
            retryable=exc.retryable,
        )

    @app.exception_handler(ContractValidationError)
    def contract_error(_request: Request, exc: ContractValidationError) -> JSONResponse:
        return _error(exc.reason_code, 422)

    @app.exception_handler(RequestValidationError)
    def request_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error("invalid_request", 422)

    @app.exception_handler(PersistenceError)
    def persistence_error(_request: Request, _exc: PersistenceError) -> JSONResponse:
        return _error("persistence_unavailable", 503, retryable=True)

    @app.exception_handler(Exception)
    def internal_error(_request: Request, _exc: Exception) -> JSONResponse:
        return _error("internal_error", 500)

    @app.post("/v1/operations", status_code=202)
    def submit_operation(
        body: SubmitOperationSchema,
        identity: Identity,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
    ) -> dict[str, object]:
        operation = service.submit(
            identity=identity,
            idempotency_key=idempotency_key,
            request=SubmitOperationRequest(
                effect=EffectRef(
                    provider=body.effect.provider,
                    action=body.effect.action,
                    version=body.effect.version,
                ),
                arguments=bounded_json_from_plain(body.arguments),
                metadata=tuple(sorted(body.metadata.items())),
                deployment_environment=body.deployment_environment,
            ),
            correlation_id=correlation_id,
        )
        return operation.to_wire()

    @app.get("/v1/operations/{operation_id}")
    def get_operation(operation_id: str, identity: Identity) -> dict[str, object]:
        return service.get_operation(
            identity, OpaqueId.from_wire(operation_id)
        ).to_wire()

    @app.get("/v1/operations/{operation_id}/audit")
    def get_audit(
        operation_id: str,
        identity: Identity,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, object]:
        return service.audit_page(
            identity=identity,
            operation_id=OpaqueId.from_wire(operation_id),
            after_sequence=after_sequence,
            limit=limit,
        ).to_wire()

    @app.get("/v1/operator/operations")
    def search_operations(
        identity: Identity,
        state: str | None = None,
        attention: bool = False,
        provider: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, object]:
        return service.search_operations(
            identity,
            OperationSearch(
                state=state,
                attention=attention,
                provider=provider,
                created_from=created_from,
                created_to=created_to,
                cursor=cursor,
                limit=limit,
            ),
        ).to_wire()

    @app.get("/v1/operator/overview")
    def operator_overview(identity: Identity) -> dict[str, object]:
        return service.operator_overview(identity).to_wire()

    @app.get("/v1/operator/operations/{operation_id}")
    def reconstruct_operation(
        operation_id: str, identity: Identity
    ) -> dict[str, object]:
        return service.reconstruct(identity, OpaqueId.from_wire(operation_id)).to_wire()

    @app.post("/v1/operator/operations/{operation_id}/semantic-summary")
    def summarize_operation(
        operation_id: str,
        _body: SemanticSummaryRequestSchema,
        identity: Identity,
    ) -> dict[str, object]:
        return service.semantic_summary(
            identity, OpaqueId.from_wire(operation_id)
        ).to_wire()

    @app.post("/v1/operator/operations/{operation_id}/approval", status_code=202)
    def decide_approval(
        operation_id: str,
        body: ApprovalActionSchema,
        identity: Identity,
        action_key: Annotated[str, Header(alias="Idempotency-Key")],
        correlation_id: Annotated[
            str,
            Header(
                alias="X-Correlation-ID",
                min_length=1,
                max_length=200,
                pattern=r".*\S.*",
            ),
        ],
    ) -> dict[str, object]:
        return service.decide_approval(
            identity=identity,
            operation_id=OpaqueId.from_wire(operation_id),
            approval_id=OpaqueId.from_wire(body.approval_id),
            expected_version=body.expected_version,
            decision=ApprovalState(body.decision),
            reason=body.reason,
            action_key=action_key,
            correlation_id=correlation_id,
        ).to_wire()

    @app.post("/v1/operator/operations/{operation_id}/verification", status_code=202)
    def request_verification(
        operation_id: str,
        body: OperatorActionSchema,
        identity: Identity,
        action_key: Annotated[str, Header(alias="Idempotency-Key")],
        correlation_id: Annotated[
            str,
            Header(
                alias="X-Correlation-ID",
                min_length=1,
                max_length=200,
                pattern=r".*\S.*",
            ),
        ],
    ) -> dict[str, object]:
        return service.request_verification(
            identity=identity,
            operation_id=OpaqueId.from_wire(operation_id),
            expected_version=body.expected_version,
            reason_code=body.reason,
            action_key=action_key,
            correlation_id=correlation_id,
        ).to_wire()

    def compensation_action(
        operation_id: str,
        body: OperatorActionSchema,
        identity: AuthenticatedIdentity,
        action_key: str,
        correlation_id: str,
        *,
        retry: bool = False,
        escalate: bool = False,
    ) -> dict[str, object]:
        return service.compensate(
            identity=identity,
            operation_id=OpaqueId.from_wire(operation_id),
            expected_version=body.expected_version,
            action_key=action_key,
            reason_code=body.reason,
            correlation_id=correlation_id,
            retry=retry,
            escalate=escalate,
        ).to_wire()

    @app.post("/v1/operator/operations/{operation_id}/compensation", status_code=202)
    def start_compensation(
        operation_id: str,
        body: OperatorActionSchema,
        identity: Identity,
        action_key: Annotated[str, Header(alias="Idempotency-Key")],
        correlation_id: Annotated[
            str,
            Header(
                alias="X-Correlation-ID",
                min_length=1,
                max_length=200,
                pattern=r".*\S.*",
            ),
        ],
    ) -> dict[str, object]:
        return compensation_action(
            operation_id, body, identity, action_key, correlation_id
        )

    @app.post(
        "/v1/operator/operations/{operation_id}/compensation/retry",
        status_code=202,
    )
    def retry_compensation(
        operation_id: str,
        body: OperatorActionSchema,
        identity: Identity,
        action_key: Annotated[str, Header(alias="Idempotency-Key")],
        correlation_id: Annotated[
            str,
            Header(
                alias="X-Correlation-ID",
                min_length=1,
                max_length=200,
                pattern=r".*\S.*",
            ),
        ],
    ) -> dict[str, object]:
        return compensation_action(
            operation_id, body, identity, action_key, correlation_id, retry=True
        )

    @app.post(
        "/v1/operator/operations/{operation_id}/compensation/escalate",
        status_code=202,
    )
    def escalate_compensation(
        operation_id: str,
        body: OperatorActionSchema,
        identity: Identity,
        action_key: Annotated[str, Header(alias="Idempotency-Key")],
        correlation_id: Annotated[
            str,
            Header(
                alias="X-Correlation-ID",
                min_length=1,
                max_length=200,
                pattern=r".*\S.*",
            ),
        ],
    ) -> dict[str, object]:
        return compensation_action(
            operation_id, body, identity, action_key, correlation_id, escalate=True
        )

    return app
