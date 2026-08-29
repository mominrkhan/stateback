import errorFixture from "../test/contract-fixtures/error-v1.json";
import listFixture from "../test/contract-fixtures/operation-list-v1.json";
import { ApiError, ClientFailure } from "./errors";
import { createOperatorClient } from "./client";
import type { CommandAttempt } from "./types";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("operator client", () => {
  it("serializes list filters and sends opaque bearer token without content type", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(listFixture));
    const client = createOperatorClient({ token: () => "  opaque token  ", fetcher });
    await client.list({ state: "UNKNOWN", cursor: "a+b" });
    expect(fetcher).toHaveBeenCalledOnce();
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/v1/operator/operations?state=UNKNOWN&cursor=a%2Bb");
    expect(init?.headers).toEqual({ Authorization: "Bearer   opaque token  " });
  });

  it("loads the authenticated read-only overview through its strict parser", async () => {
    const payload = {
      contract_version: "v1", total_operations: 0,
      attention: { awaiting_approval: 0, unknown: 0, manual_intervention: 0, compensation_issues: 0 },
      active: { executing: 0, verifying: 0, compensating: 0 }, recent_operations: [],
      providers: [{ provider: "github", configured: false, supported_effects: [{ provider: "github", action: "create_issue", version: "v1" }] }],
    };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(payload));
    const client = createOperatorClient({ token: () => "token", fetcher });
    expect((await client.overview()).providers[0].configured).toBe(false);
    expect(fetcher.mock.calls[0][0]).toBe("/v1/operator/overview");
  });

  it.each(["approve", "reject", "verify", "compensate", "retry_compensation", "escalate_compensation"] as const)("submits %s with caller-owned stable command identity", async (actionKey) => {
    const operation = listFixture.items[0]; const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(operation, 202));
    const client = createOperatorClient({ token: () => "token", fetcher });
    const attempt: CommandAttempt = Object.freeze({ operationId: operation.operation_id, actionKey, expectedVersion: 2, approvalId: actionKey === "approve" || actionKey === "reject" ? "approval-1" : undefined, reason: "reviewed", idempotencyKey: "same-idempotency", correlationId: "same-correlation" });
    await client.command(attempt);
    const [, init] = fetcher.mock.calls[0];
    expect(init?.headers).toMatchObject({ "Idempotency-Key": "same-idempotency", "X-Correlation-ID": "same-correlation", "Content-Type": "application/json" });
    expect(JSON.parse(String(init?.body))).toMatchObject({ expected_version: 2, reason: "reviewed" });
    expect(attempt.idempotencyKey).toBe("same-idempotency");
  });

  it("preserves structured API errors and announces 401", async () => {
    const unauthorized = vi.fn(); const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(errorFixture, 401));
    const client = createOperatorClient({ token: () => "token", fetcher, onUnauthorized: unauthorized });
    await expect(client.list()).rejects.toMatchObject({ status: 401, code: "stale_version", retryable: false } satisfies Partial<ApiError>);
    expect(unauthorized).toHaveBeenCalledOnce();
  });

  it("clears authentication even when a 401 body is malformed", async () => {
    const unauthorized = vi.fn();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response("not json", { status: 401 }));
    const client = createOperatorClient({ token: () => "token", fetcher, onUnauthorized: unauthorized });
    await expect(client.list()).rejects.toMatchObject({ kind: "malformed_response" } satisfies Partial<ClientFailure>);
    expect(unauthorized).toHaveBeenCalledOnce();
  });

  it("registers and releases every internal request controller", async () => {
    const controller = new AbortController();
    const createAbortController = vi.fn(() => controller);
    const releaseAbortController = vi.fn();
    const client = createOperatorClient({
      token: () => "token",
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(response(listFixture)),
      createAbortController,
      releaseAbortController,
    });
    await client.list();
    expect(createAbortController).toHaveBeenCalledOnce();
    expect(releaseAbortController).toHaveBeenCalledWith(controller);
  });

  it("marks malformed command receipts indeterminate", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({ contract_version: "v1" }, 202));
    const client = createOperatorClient({ token: () => "token", fetcher });
    await expect(client.command({ operationId: "opaque", actionKey: "verify", expectedVersion: 2, reason: "reviewed", idempotencyKey: "id", correlationId: "correlation" }))
      .rejects.toMatchObject({ kind: "malformed_response", indeterminate: true } satisfies Partial<ClientFailure>);
  });

  it("uses injectable deadlines without automatic retry", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn<typeof fetch>((_input, init) => new Promise((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true })));
    const client = createOperatorClient({ token: () => "token", fetcher, deadlines: { readMs: 5 } });
    const assertion = expect(client.list()).rejects.toMatchObject({ kind: "timeout", indeterminate: false } satisfies Partial<ClientFailure>);
    await vi.advanceTimersByTimeAsync(5);
    await assertion;
    expect(fetcher).toHaveBeenCalledOnce(); vi.useRealTimers();
  });
});
