import type { Operation, Reconstruction, SemanticSummary } from "./types";

export interface OperatorApi {
  list(): Promise<Operation[]>;
  reconstruct(operationId: string): Promise<Reconstruction>;
  summarize(operationId: string): Promise<SemanticSummary>;
  control(
    operation: Operation,
    action: string,
    reason: string,
  ): Promise<Operation>;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`Invalid ${label} response`);
  }
  return value as Record<string, unknown>;
}

export function parseOperation(value: unknown): Operation {
  const raw = object(value, "operation");
  if (
    raw.contract_version !== "v1" ||
    typeof raw.operation_id !== "string" ||
    typeof raw.state !== "string" ||
    typeof raw.version !== "number" ||
    typeof raw.created_at !== "string" ||
    typeof raw.updated_at !== "string"
  ) {
    throw new Error("Unsupported or malformed operation response");
  }
  object(raw.intent, "intent");
  return raw as unknown as Operation;
}

export function parseSemanticSummary(value: unknown): SemanticSummary {
  const raw = object(value, "semantic summary");
  const provenance = object(raw.provenance, "semantic provenance");
  const statuses = new Set(["AVAILABLE", "ABSTAINED", "UNAVAILABLE", "INVALID"]);
  const keyEventsValid = Array.isArray(raw.key_events) && raw.key_events.every((item) => {
    const event = object(item, "semantic key event");
    return Number.isInteger(event.sequence)
      && typeof event.sequence === "number"
      && event.sequence >= 1
      && typeof raw.summarized_through_sequence === "number"
      && event.sequence <= raw.summarized_through_sequence
      && typeof event.description === "string"
      && event.description.trim().length >= 1
      && event.description.length <= 500;
  });
  const uncertaintiesValid = Array.isArray(raw.unresolved_uncertainties)
    && raw.unresolved_uncertainties.length <= 20
    && raw.unresolved_uncertainties.every(
      (item) => typeof item === "string" && item.trim().length >= 1 && item.length <= 500,
    );
  const contentShapeValid = raw.status === "AVAILABLE"
    ? typeof raw.summary === "string"
      && raw.summary.trim().length >= 1
      && raw.summary.length <= 2000
      && typeof raw.confidence === "number"
      && raw.confidence >= 0.5
    : raw.summary === null
      && raw.confidence === null
      && Array.isArray(raw.key_events)
      && raw.key_events.length === 0
      && Array.isArray(raw.unresolved_uncertainties)
      && raw.unresolved_uncertainties.length === 0;
  if (
    raw.contract_version !== "v1" ||
    raw.advisory !== true ||
    typeof raw.status !== "string" || !statuses.has(raw.status) ||
    !contentShapeValid ||
    !Array.isArray(raw.key_events) || raw.key_events.length > 20 ||
    !keyEventsValid ||
    !uncertaintiesValid ||
    !(typeof raw.confidence === "number" || raw.confidence === null) ||
    (typeof raw.confidence === "number" && (!Number.isFinite(raw.confidence) || raw.confidence < 0 || raw.confidence > 1)) ||
    !Number.isInteger(raw.summarized_operation_version) ||
    typeof raw.summarized_operation_version !== "number" || raw.summarized_operation_version < 1 ||
    !Number.isInteger(raw.summarized_through_sequence) ||
    typeof raw.summarized_through_sequence !== "number" || raw.summarized_through_sequence < 0 ||
    typeof raw.reason_code !== "string" || raw.reason_code.length < 1 || raw.reason_code.length > 200 ||
    !(provenance.provider === null || (typeof provenance.provider === "string" && provenance.provider.length >= 1 && provenance.provider.length <= 200)) ||
    !(provenance.model === null || (typeof provenance.model === "string" && provenance.model.length >= 1 && provenance.model.length <= 200)) ||
    provenance.prompt_version !== "audit-summary-v1" ||
    provenance.output_schema_version !== "v1"
  ) {
    throw new Error("Unsupported or malformed semantic summary response");
  }
  return raw as unknown as SemanticSummary;
}

export function createOperatorApi(baseUrl: string, token: () => string): OperatorApi {
  async function request(path: string, init?: RequestInit): Promise<unknown> {
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token()}`,
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
    const payload: unknown = await response.json();
    if (!response.ok) {
      const raw = object(payload, "error");
      const error = object(raw.error, "error");
      throw new Error(typeof error.message === "string" ? error.message : "Request failed");
    }
    return payload;
  }

  return {
    async list() {
      const raw = object(await request("/v1/operator/operations"), "list");
      if (raw.contract_version !== "v1" || !Array.isArray(raw.items)) {
        throw new Error("Unsupported or malformed list response");
      }
      return raw.items.map(parseOperation);
    },
    async reconstruct(operationId) {
      const raw = object(
        await request(`/v1/operator/operations/${operationId}`),
        "reconstruction",
      );
      if (raw.contract_version !== "v1" || !Array.isArray(raw.audit) || !Array.isArray(raw.available_actions)) {
        throw new Error("Unsupported or malformed reconstruction response");
      }
      return { ...raw, operation: parseOperation(raw.operation) } as unknown as Reconstruction;
    },
    async summarize(operationId) {
      return parseSemanticSummary(
        await request(`/v1/operator/operations/${operationId}/semantic-summary`, {
          method: "POST",
          body: JSON.stringify({ contract_version: "v1" }),
        }),
      );
    },
    async control(operation, action, reason) {
      const suffix: Record<string, string> = {
        verify: "verification",
        compensate: "compensation",
        retry_compensation: "compensation/retry",
        escalate_compensation: "compensation/escalate",
      };
      if (action === "approve" || action === "reject") {
        if (!operation.current_approval_id) throw new Error("No current approval");
        const correlationId = crypto.randomUUID();
        return parseOperation(
          await request(`/v1/operator/operations/${operation.operation_id}/approval`, {
            method: "POST",
            headers: {
              "Idempotency-Key": crypto.randomUUID(),
              "X-Correlation-ID": correlationId,
            },
            body: JSON.stringify({
              contract_version: "v1",
              approval_id: operation.current_approval_id,
              expected_version: operation.version,
              decision: action === "approve" ? "APPROVED" : "REJECTED",
              reason,
            }),
          }),
        );
      }
      const path = suffix[action];
      if (!path) throw new Error("Unsupported action");
      const correlationId = crypto.randomUUID();
      return parseOperation(
        await request(`/v1/operator/operations/${operation.operation_id}/${path}`, {
          method: "POST",
          headers: {
            "Idempotency-Key": crypto.randomUUID(),
            "X-Correlation-ID": correlationId,
          },
          body: JSON.stringify({
            contract_version: "v1",
            expected_version: operation.version,
            reason,
          }),
        }),
      );
    },
  };
}
