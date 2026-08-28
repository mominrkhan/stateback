import type { Page, Route } from "@playwright/test";

import { parseOperationPage, parseReconstruction } from "../src/api/parsers";
import type { Operation, Reconstruction } from "../src/api/types";
import listFixture from "../src/test/contract-fixtures/operation-list-v1.json" with { type: "json" };
import reconstructionFixture from "../src/test/contract-fixtures/reconstruction-empty-verifications-v1.json" with { type: "json" };

export const FIRST_ID = "00000000-0000-4000-8000-000000000001";
export const SECOND_ID = "00000000-0000-4000-8000-000000000002";
export const APPROVAL_ID = "00000000-0000-4000-8000-000000000003";
export const MANUAL_ID = "00000000-0000-4000-8000-000000000004";
export const COMPENSATION_ID = "00000000-0000-4000-8000-000000000005";
export const START_COMPENSATION_ID = "00000000-0000-4000-8000-000000000007";

export function operation(id: string, state: string): Operation {
  const value = parseOperationPage(structuredClone(listFixture)).items[0];
  return { ...value, operation_id: id, state };
}

export function reconstruction(
  current: Operation,
  availableActions: string[] = [],
): Reconstruction {
  const value = parseReconstruction(structuredClone(reconstructionFixture));
  return { ...value, operation: current, available_actions: availableActions };
}

export function approvalReconstruction(version = 3): Reconstruction {
  const current = {
    ...operation(FIRST_ID, "AWAITING_APPROVAL"),
    version,
    current_approval_id: APPROVAL_ID,
    intent: {
      ...operation(FIRST_ID, "AWAITING_APPROVAL").intent,
      arguments: {
        owner: "octo-org",
        repo: "stateback",
        title: "Review production issue",
        labels: ["safety"],
        assignees: ["operator"],
        body: "private provider body",
      },
    },
  };
  return {
    ...reconstruction(current, ["approve", "reject"]),
    approvals: [{
      contract_version: "v1",
      approval_id: APPROVAL_ID,
      operation_id: FIRST_ID,
      operation_version: version,
      intent_digest: current.intent.intent_digest,
      policy_decision_id: "00000000-0000-4000-8000-000000000006",
      state: "PENDING",
      requested_at: "2026-08-20T12:00:00.000000Z",
      expires_at: null,
      decided_at: null,
      decided_by: null,
      reason: null,
    }],
  };
}

export function compensationReconstruction(): Reconstruction {
  const current = { ...operation(COMPENSATION_ID, "COMPENSATION_FAILED"), compensation_id: APPROVAL_ID };
  return {
    ...reconstruction(current, ["retry_compensation", "escalate_compensation"]),
    compensation: {
      contract_version: "v1",
      compensation_id: APPROVAL_ID,
      original_operation_id: COMPENSATION_ID,
      kind: "BEST_EFFORT",
      state: "FAILED",
      version: 2,
      intent_digest: "compensation-intent-digest",
      arguments_mode: "INLINE",
      arguments: {},
      arguments_ref: null,
      idempotency_identity: "compensation-identity",
      requested_by: { type: "OPERATOR", id: "operator", display_name: null },
      policy_decision_id: null,
      created_at: "2026-08-20T12:00:00.000000Z",
      updated_at: "2026-08-20T12:05:00.000000Z",
    },
  };
}

export type CommandFault = "none" | "conflict" | "403" | "422" | "429" | "500" | "503" | "malformed" | "connection" | "timeout";

export interface ApiScenario {
  listError?: number;
  unauthorizedList?: boolean;
  commandFault?: CommandFault;
  commandRequests: Array<{ headers: Record<string, string>; body: string | null }>;
  reconstructionReads: number;
  listRequests: number;
  listQueries: string[];
  listGate?: Promise<void>;
  commandAccepted?: boolean;
}

export function scenario(options: Partial<ApiScenario> = {}): ApiScenario {
  return {
    commandFault: "none",
    commandRequests: [],
    reconstructionReads: 0,
    listRequests: 0,
    listQueries: [],
    ...options,
  };
}

function errorEnvelope(status: number) {
  const code = status === 409 ? "stale_version"
    : status === 401 ? "unauthorized"
      : status === 403 ? "forbidden"
        : status === 422 ? "validation_error"
          : status === 429 ? "rate_limited"
            : "backend_unavailable";
  return {
    contract_version: "v1",
    error: {
      code,
      message: status === 409 ? "Version changed" : status === 401 ? "Token rejected" : code.replaceAll("_", " "),
      retryable: status >= 500,
      correlation_id: "safe-correlation",
    },
  };
}

function detailFor(id: string, reads: number, commandAccepted = false): Reconstruction {
  if (commandAccepted && (id === FIRST_ID || id === MANUAL_ID)) {
    return reconstruction({ ...operation(id, "READY"), version: 4 }, []);
  }
  if (id === FIRST_ID) return approvalReconstruction(reads > 1 ? 4 : 3);
  if (id === MANUAL_ID) return reconstruction(operation(MANUAL_ID, "MANUAL_INTERVENTION"), ["verify"]);
  if (id === COMPENSATION_ID) return compensationReconstruction();
  if (id === START_COMPENSATION_ID) return reconstruction(operation(START_COMPENSATION_ID, "SUCCEEDED"), ["compensate"]);
  return reconstruction(operation(id, "UNKNOWN"), []);
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export async function installApi(page: Page, state: ApiScenario) {
  await page.route("**/v1/operator/operations**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (request.method() === "POST") {
      state.commandRequests.push({ headers: request.headers(), body: request.postData() });
      const attempt = state.commandRequests.length;
      if (attempt === 1 && state.commandFault && state.commandFault !== "none") {
        if (state.commandFault === "malformed") {
          await route.fulfill({ status: 200, contentType: "application/json", body: "{" });
          return;
        }
        if (state.commandFault === "connection") {
          await route.abort("connectionreset");
          return;
        }
        if (state.commandFault === "timeout") {
          await new Promise((resolve) => setTimeout(resolve, 31_000));
          await route.abort("timedout");
          return;
        }
        const status = state.commandFault === "conflict" ? 409 : Number(state.commandFault);
        await fulfillJson(route, errorEnvelope(status), status);
        return;
      }
      state.commandAccepted = true;
      await fulfillJson(route, { ...operation(FIRST_ID, "READY"), version: 4 }, 202);
      return;
    }

    const detailMatch = /^\/v1\/operator\/operations\/([^/]+)$/.exec(path);
    if (detailMatch) {
      state.reconstructionReads += 1;
      await fulfillJson(route, detailFor(
        decodeURIComponent(detailMatch[1]),
        state.reconstructionReads,
        state.commandAccepted,
      ));
      return;
    }

    state.listRequests += 1;
    const listGate = state.listGate;
    state.listGate = undefined;
    if (listGate) await listGate;
    state.listQueries.push(url.search);
    if (state.unauthorizedList) {
      state.unauthorizedList = false;
      await fulfillJson(route, errorEnvelope(401), 401);
      return;
    }
    if (state.listError) {
      const status = state.listError;
      state.listError = undefined;
      await fulfillJson(route, errorEnvelope(status), status);
      return;
    }
    const stateFilter = url.searchParams.get("state");
    const cursor = url.searchParams.get("cursor");
    if (stateFilter === "AWAITING_APPROVAL") {
      await fulfillJson(route, { contract_version: "v1", items: [operation(FIRST_ID, "AWAITING_APPROVAL")], next_cursor: null });
      return;
    }
    if (stateFilter === "MANUAL_INTERVENTION") {
      await fulfillJson(route, { contract_version: "v1", items: [operation(MANUAL_ID, stateFilter)], next_cursor: null });
      return;
    }
    if (stateFilter === "COMPENSATION_FAILED") {
      await fulfillJson(route, { contract_version: "v1", items: [operation(COMPENSATION_ID, stateFilter)], next_cursor: null });
      return;
    }
    if (stateFilter) {
      await fulfillJson(route, { contract_version: "v1", items: [], next_cursor: null });
      return;
    }
    await fulfillJson(route, {
      contract_version: "v1",
      items: [cursor ? operation(SECOND_ID, "SUCCEEDED") : operation(FIRST_ID, "UNKNOWN")],
      next_cursor: cursor ? null : "opaque+cursor/=",
    });
  });
}

export async function login(page: Page, path = "/") {
  await page.goto(path);
  await page.getByLabel("Access token").fill("browser-test-token");
  await page.getByRole("button", { name: "Sign in" }).click();
}
