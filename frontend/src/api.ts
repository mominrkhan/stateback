import type { Operation, Reconstruction } from "./types";

export interface OperatorApi {
  list(): Promise<Operation[]>;
  reconstruct(operationId: string): Promise<Reconstruction>;
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
