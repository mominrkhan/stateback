export interface ApiErrorDetails {
  status: number;
  code: string;
  safeMessage: string;
  retryable: boolean;
  correlationId: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly correlationId: string | null;

  constructor(details: ApiErrorDetails) {
    super(details.safeMessage);
    this.name = "ApiError";
    this.status = details.status;
    this.code = details.code;
    this.retryable = details.retryable;
    this.correlationId = details.correlationId;
  }
}

export type ClientFailureKind = "timeout" | "network" | "malformed_response";

export class ClientFailure extends Error {
  constructor(readonly kind: ClientFailureKind, message: string, readonly indeterminate: boolean) {
    super(message);
    this.name = "ClientFailure";
  }
}

export class ParseFailure extends Error {
  constructor(readonly field: string, reason: string) {
    super(`${field}: ${reason}`);
    this.name = "ParseFailure";
  }
}
