import reconstructionFixture from "../../test/contract-fixtures/reconstruction-empty-verifications-v1.json";
import type { OperatorClient } from "../../api/client";
import { ApiError, ClientFailure } from "../../api/errors";
import { parseReconstruction } from "../../api/parsers";
import type { CommandAttempt, Operation, Reconstruction } from "../../api/types";
import { CommandAttemptRegistry } from "./attemptRegistry";
import { CommandController } from "./commandController";

function reconstruction(actions: string[] = ["verify"], version = 2): Reconstruction {
  const base = parseReconstruction(reconstructionFixture);
  return { ...base, operation: { ...base.operation, version }, available_actions: actions };
}
function client(command: (attempt: CommandAttempt) => Promise<Operation>, reconstruct: () => Promise<Reconstruction>): OperatorClient {
  return { overview: vi.fn(), list: vi.fn(), semanticSummary: vi.fn(), command: vi.fn(command), reconstruct: vi.fn(reconstruct) };
}
function ids(): () => string { let value = 0; return () => `id-${++value}`; }

describe("CommandController", () => {
  it("creates and freezes normalized identity only at confirmation, then reloads authoritative state", async () => {
    const registry = new CommandAttemptRegistry(); const fresh = reconstruction([], 3); let observed: CommandAttempt | undefined;
    const api = client(async (attempt) => { observed = attempt; return fresh.operation; }, async () => fresh);
    const controller = new CommandController(api, { registry, makeId: ids() });
    expect(registry.get(fresh.operation.operation_id)).toBeUndefined();
    await controller.confirm(reconstruction(), "verify", "  reviewed  ");
    expect(observed).toMatchObject({ reason: "reviewed", idempotencyKey: "id-1", correlationId: "id-2", expectedVersion: 2 });
    expect(Object.isFrozen(observed)).toBe(true);
    expect(controller.state.phase).toBe("accepted"); expect(controller.state.reconstruction).toBe(fresh);
    expect(registry.get(fresh.operation.operation_id)).toBeUndefined();
  });

  it("retains an indeterminate attempt and retries the exact same object only after unchanged reload", async () => {
    const baseline = reconstruction(); let calls = 0; const received: CommandAttempt[] = [];
    const api = client(async (attempt) => { received.push(attempt); if (++calls === 1) throw new ClientFailure("timeout", "timed out", true); return baseline.operation; }, async () => calls === 1 ? baseline : reconstruction([], 3));
    const controller = new CommandController(api, { registry: new CommandAttemptRegistry(), makeId: ids() });
    await controller.confirm(baseline, "verify", "reviewed");
    expect(controller.state).toMatchObject({ phase: "indeterminate", retrySameRequest: true, controlsDisabled: true, readGeneration: 1 });
    await controller.retrySame(baseline.operation.operation_id);
    expect(received[1]).toBe(received[0]); expect(controller.state.phase).toBe("accepted");
  });

  it("reloads a 409, preserves reason, and classifies non-ambiguous errors distinctly", async () => {
    for (const [status, phase] of [[409, "conflict"], [403, "forbidden"], [422, "validation-error"], [429, "rate-limited"]] as const) {
      const api = client(async () => { throw new ApiError({ status, code: "fixture", safeMessage: "fixture error", retryable: false, correlationId: null }); }, async () => reconstruction([], 4));
      const controller = new CommandController(api, { registry: new CommandAttemptRegistry(), makeId: ids() });
      await controller.confirm(reconstruction(), "verify", "preserve me");
      expect(controller.state.phase).toBe(phase); expect(controller.state.reason).toBe("preserve me");
      expect(api.reconstruct).toHaveBeenCalledTimes(status === 409 ? 1 : 0);
    }
  });

  it("treats 500/503 as indeterminate and clears retry when authoritative eligibility changes", async () => {
    for (const status of [500, 503]) {
      const api = client(async () => { throw new ApiError({ status, code: "backend", safeMessage: "backend failure", retryable: status === 503, correlationId: null }); }, async () => reconstruction([], 3));
      const registry = new CommandAttemptRegistry(); const controller = new CommandController(api, { registry, makeId: ids() });
      await controller.confirm(reconstruction(), "verify", "reviewed");
      expect(controller.state).toMatchObject({ phase: "authoritative-reloaded", retrySameRequest: false, controlsDisabled: false });
      expect(registry.get(reconstruction().operation.operation_id)).toBeUndefined();
    }
  });

  it("requires ambiguity acknowledgement to abandon and rotates identifiers on a new review", async () => {
    const baseline = reconstruction(); const api = client(async () => { throw new ClientFailure("network", "lost", true); }, async () => baseline);
    const registry = new CommandAttemptRegistry(); const controller = new CommandController(api, { registry, makeId: ids() });
    await controller.confirm(baseline, "verify", "first"); const first = registry.get(baseline.operation.operation_id);
    expect(() => controller.reviewNew(baseline.operation.operation_id, false)).toThrow("ambiguity acknowledgement");
    expect(controller.reviewNew(baseline.operation.operation_id, true)).toBe("first");
    await controller.confirm(baseline, "verify", "second"); const second = registry.get(baseline.operation.operation_id);
    expect(second?.idempotencyKey).not.toBe(first?.idempotencyKey); expect(second?.correlationId).not.toBe(first?.correlationId);
  });

  it("rejects unavailable actions without creating an attempt", async () => {
    const registry = new CommandAttemptRegistry(); const controller = new CommandController(client(async () => reconstruction().operation, async () => reconstruction()), { registry, makeId: ids() });
    await expect(controller.confirm(reconstruction([]), "verify", "reviewed")).rejects.toThrow("not available");
    expect(registry.get(reconstruction().operation.operation_id)).toBeUndefined();
  });
});
