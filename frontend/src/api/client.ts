import { ApiError, ClientFailure, ParseFailure } from "./errors";
import { parseApiError, parseOperation, parseOperationPage, parseOperatorOverview, parseReconstruction, parseSemanticSummary } from "./parsers";
import { operationQuery, type OperationFilters } from "./query";
import type { CommandAttempt, Operation, OperationPage, OperatorOverview, Reconstruction, SemanticSummary } from "./types";

export interface RequestDeadlines { readMs: number; semanticMs: number; commandMs: number }
export interface OperatorClientOptions {
  token: () => string;
  baseUrl?: string;
  fetcher?: typeof fetch;
  deadlines?: Partial<RequestDeadlines>;
  onUnauthorized?: () => void;
  createAbortController?: () => AbortController;
  releaseAbortController?: (controller: AbortController) => void;
}
export interface OperatorClient {
  list(filters?: OperationFilters, signal?: AbortSignal): Promise<OperationPage>;
  overview(signal?: AbortSignal): Promise<OperatorOverview>;
  reconstruct(operationId: string, signal?: AbortSignal): Promise<Reconstruction>;
  semanticSummary(operationId: string, signal?: AbortSignal): Promise<SemanticSummary>;
  command(attempt: CommandAttempt, signal?: AbortSignal): Promise<Operation>;
}

const DEFAULT_DEADLINES: RequestDeadlines = { readMs: 15_000, semanticMs: 30_000, commandMs: 30_000 };

function operationPath(operationId: string): string {
  if (!operationId || /[\u0000-\u001f\u007f/]/u.test(operationId)) throw new TypeError("Invalid operation ID");
  return `/v1/operator/operations/${encodeURIComponent(operationId)}`;
}

export function createOperatorClient(options: OperatorClientOptions): OperatorClient {
  const fetcher = options.fetcher ?? fetch;
  const baseUrl = options.baseUrl ?? "";
  const deadlines: RequestDeadlines = {
    readMs: options.deadlines?.readMs ?? DEFAULT_DEADLINES.readMs,
    semanticMs: options.deadlines?.semanticMs ?? DEFAULT_DEADLINES.semanticMs,
    commandMs: options.deadlines?.commandMs ?? DEFAULT_DEADLINES.commandMs,
  };

  async function request(path: string, deadlineMs: number, indeterminate: boolean, init: RequestInit, external?: AbortSignal): Promise<unknown> {
    const token = options.token();
    if (typeof token !== "string" || token.length === 0) throw new TypeError("Authentication token is required");
    const controller = options.createAbortController?.() ?? new AbortController(); let timedOut = false;
    const abort = () => controller.abort(external?.reason);
    if (external?.aborted) abort(); else external?.addEventListener("abort", abort, { once: true });
    const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, deadlineMs);
    let response: Response;
    try {
      response = await fetcher(`${baseUrl}${path}`, { ...init, signal: controller.signal, headers: { Authorization: `Bearer ${token}`, ...init.headers } });
    } catch (cause) {
      if (external?.aborted) throw cause;
      throw new ClientFailure(timedOut ? "timeout" : "network", timedOut ? "Request timed out" : "Network request failed", indeterminate);
    } finally {
      window.clearTimeout(timer); external?.removeEventListener("abort", abort);
      options.releaseAbortController?.(controller);
    }
    if (response.status === 401) options.onUnauthorized?.();
    let payload: unknown;
    try { payload = await response.json(); } catch { throw new ClientFailure("malformed_response", "Server returned malformed JSON", indeterminate); }
    if (!response.ok) {
      try {
        const details = parseApiError(payload, response.status);
        throw new ApiError(details);
      } catch (cause) {
        if (cause instanceof ApiError) throw cause;
        throw new ClientFailure("malformed_response", "Server returned a malformed error response", indeterminate);
      }
    }
    return payload;
  }

  function parse<T>(payload: unknown, parser: (value: unknown) => T, indeterminate: boolean): T {
    try { return parser(payload); } catch (cause) {
      if (cause instanceof ParseFailure) throw new ClientFailure("malformed_response", cause.message, indeterminate);
      throw cause;
    }
  }

  return {
    async overview(signal) {
      const payload = await request("/v1/operator/overview", deadlines.readMs, false, { method: "GET" }, signal);
      return parse(payload, parseOperatorOverview, false);
    },
    async list(filters = {}, signal) {
      const payload = await request(`/v1/operator/operations${operationQuery(filters)}`, deadlines.readMs, false, { method: "GET" }, signal);
      return parse(payload, parseOperationPage, false);
    },
    async reconstruct(operationId, signal) {
      const payload = await request(operationPath(operationId), deadlines.readMs, false, { method: "GET" }, signal);
      return parse(payload, parseReconstruction, false);
    },
    async semanticSummary(operationId, signal) {
      const payload = await request(`${operationPath(operationId)}/semantic-summary`, deadlines.semanticMs, false, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contract_version: "v1" }) }, signal);
      return parse(payload, parseSemanticSummary, false);
    },
    async command(attempt, signal) {
      const suffix = attempt.actionKey === "approve" || attempt.actionKey === "reject" ? "approval" : attempt.actionKey === "verify" ? "verification" : attempt.actionKey === "compensate" ? "compensation" : attempt.actionKey === "retry_compensation" ? "compensation/retry" : "compensation/escalate";
      if ((attempt.actionKey === "approve" || attempt.actionKey === "reject") && !attempt.approvalId) throw new TypeError("Approval command requires approvalId");
      const body = attempt.actionKey === "approve" || attempt.actionKey === "reject"
        ? { contract_version: "v1", approval_id: attempt.approvalId, expected_version: attempt.expectedVersion, decision: attempt.actionKey === "approve" ? "APPROVED" : "REJECTED", reason: attempt.reason }
        : { contract_version: "v1", expected_version: attempt.expectedVersion, reason: attempt.reason };
      const payload = await request(`${operationPath(attempt.operationId)}/${suffix}`, deadlines.commandMs, true, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": attempt.idempotencyKey, "X-Correlation-ID": attempt.correlationId }, body: JSON.stringify(body) }, signal);
      return parse(payload, parseOperation, true);
    },
  };
}
