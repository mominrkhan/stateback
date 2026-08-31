import AxeBuilder from "@axe-core/playwright";
import { expect, test as base, type Locator, type Page } from "@playwright/test";

import {
  COMPENSATION_ID,
  FIRST_ID,
  MANUAL_ID,
  SECOND_ID,
  START_COMPENSATION_ID,
  installApi,
  login,
  scenario,
  type ApiScenario,
  type CommandFault,
} from "./fixtures";

const APP_ORIGIN = "http://127.0.0.1:4173";

const test = base.extend<{ cleanRuntime: void }>({
  cleanRuntime: [async ({ page }, use) => {
    const runtimeErrors: string[] = [];
    const foreignOrigins: string[] = [];
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const expectedApiFailure = message.text().startsWith("Failed to load resource:")
        && message.location().url.startsWith(`${APP_ORIGIN}/v1/operator/`);
      if (!expectedApiFailure) runtimeErrors.push(message.text());
    });
    page.on("pageerror", (error) => runtimeErrors.push(error.message));
    page.on("request", (request) => {
      const url = new URL(request.url());
      if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== APP_ORIGIN) {
        foreignOrigins.push(url.origin);
      }
    });
    await use();
    expect(runtimeErrors, "browser console/page errors").toEqual([]);
    expect(foreignOrigins, "unexpected network origins").toEqual([]);
  }, { auto: true }],
});

async function expectAxeClean(page: Page) {
  await expect(page.locator('[data-sonner-toast][data-removed="true"]')).toHaveCount(0);
  const result = await new AxeBuilder({ page })
    .exclude("[data-base-ui-focus-guard]")
    .analyze();
  expect(result.violations, result.violations.map((item) => `${item.id}: ${item.help}`).join("\n")).toEqual([]);
}

async function expectInsideViewport(locator: Locator, page: Page, includeVertical = true) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width);
  if (includeVertical) {
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height);
  }
}

async function expectTouchTarget(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(44);
  expect(box!.height).toBeGreaterThanOrEqual(44);
}

async function navigateInSession(page: Page, path: string) {
  await page.evaluate((href) => {
    window.history.pushState(null, "", href);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

async function openApproval(page: Page) {
  await page.getByRole("link", { name: /create issue with github/i }).click();
  await expect(page.getByRole("heading", { name: "Create issue" })).toBeVisible();
}

async function openFilters(page: Page) {
  const apply = page.getByRole("button", { name: "Apply filters" });
  if (!await apply.isVisible()) await page.getByRole("button", { name: "Filters" }).click();
}

async function submitDetailCommand(page: Page, state: ApiScenario) {
  await page.getByRole("button", { name: "Request verification" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Operator reason").fill("operator verified provider state");
  await dialog.getByRole("button", { name: "Request verification" }).click();
  await expect.poll(() => state.commandRequests.length).toBe(1);
}

test("manual authentication keeps production credentials memory-only and root is Overview", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await page.goto("/");
  await expectAxeClean(page);
  await page.getByLabel("Access token").fill("browser-test-token");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeFocused();
  await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length, html: document.documentElement.innerHTML }))).toEqual({
    local: 0,
    session: 0,
    html: expect.not.stringContaining("browser-test-token"),
  });

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Sign in to Stateback" })).toBeFocused();
  await expect(page.getByText(FIRST_ID)).toHaveCount(0);
});

test("command palette supports keyboard navigation and exact operation IDs", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/");
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();

  await page.keyboard.press("Meta+K");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await palette.getByLabel("Search commands").fill(FIRST_ID);
  await palette.getByLabel("Search commands").press("Enter");
  await expect(page).toHaveURL(new RegExp(`/operations/${FIRST_ID}$`));
  await expect(page.getByRole("heading", { name: "Create issue" })).toBeVisible();

  await page.keyboard.press("Meta+K");
  await palette.getByLabel("Search commands").fill("providers");
  await palette.getByRole("link", { name: /providers/i }).click();
  await expect(page).toHaveURL(/\/providers$/);
  await expect(page.getByRole("heading", { name: "Providers", level: 1 })).toBeFocused();
});

test("a 401 clears the session and returns focus to access", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/operations");
  await expect(page.getByText(FIRST_ID)).toBeVisible();
  state.unauthorizedList = true;
  await openFilters(page);
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("alert")).toContainText(/session expired/i);
  await expectAxeClean(page);
  await expect(page.getByRole("heading", { name: "Sign in to Stateback" })).toBeFocused();
  await expect(page).toHaveURL(/\/$/);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
});

test("local bootstrap survives same-tab refresh and clears on logout", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  const token = "a".repeat(43);
  await page.goto(`/#stateback-bootstrap=${token}`);
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeFocused();
  await expect(page).toHaveURL(/\/$/);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 1 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0);
});

test("operations preserve exact filters, backend order, cursor history, and detail navigation", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/operations");

  await openFilters(page);
  await page.getByRole("combobox", { name: "State", exact: true }).selectOption("NEEDS_ATTENTION");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect.poll(() => state.listQueries.at(-1)).toContain("attention=true");
  await expect(page).toHaveURL(/\/operations\?attention=true&limit=50$/);

  await openFilters(page);
  await page.getByRole("combobox", { name: "State", exact: true }).selectOption("UNKNOWN");
  await page.getByLabel("Provider (exact)").fill("github");
  await page.getByLabel("Created from (UTC)").fill("2026-08-19T12:00");
  await page.getByLabel("Created to (UTC, inclusive)").fill("2026-08-20T12:00");
  await page.getByLabel("Results per page").fill("25");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect.poll(() => state.listQueries.at(-1)).toContain("state=UNKNOWN");
  const applied = new URLSearchParams(state.listQueries.at(-1));
  expect(Object.fromEntries(applied)).toEqual({
    state: "UNKNOWN",
    provider: "github",
    created_from: "2026-08-19T12:00:00.000Z",
    created_to: "2026-08-20T12:00:00.000Z",
    limit: "25",
  });

  await openFilters(page);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByText(FIRST_ID)).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText(SECOND_ID)).toBeVisible();
  expect(new URLSearchParams(state.listQueries.at(-1)).get("cursor")).toBe("opaque+cursor/=");
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page.getByText(FIRST_ID)).toBeVisible();

  await page.getByRole("link", { name: /create issue/i }).click();
  await expect(page).toHaveURL(new RegExp(`/operations/${FIRST_ID}$`));
  await expect(page.getByRole("heading", { name: "Create issue with GitHub", level: 1 })).toBeFocused();
  for (const heading of ["Summary", "Execution attempts", "Evidence", "Verification and reconciliation", "Compensation", "Durable audit"]) {
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
  await page.locator(".operation-detail__back").click();
  await expect(page).toHaveURL(/\/operations$/);
  await expect(page.getByRole("heading", { name: "Operations", level: 1 })).toBeFocused();
  await expect(page.getByRole("heading", { name: "Sign in to Stateback" })).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/operations/${FIRST_ID}$`));
  await expect(page.getByRole("heading", { name: "Create issue with GitHub", level: 1 })).toBeFocused();
});

test("approval dialog is keyboard-safe and submits the exact binding", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/approvals");
  await openApproval(page);
  const trigger = page.getByRole("button", { name: "Approve create issue" });
  await page.getByLabel("Operator reason").fill("reviewed immutable binding");
  await trigger.focus();
  await page.keyboard.press("Enter");
  let dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Confirm approval" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await page.getByRole("button", { name: "Reject create issue" }).click();
  await expect(page.getByRole("heading", { name: "Confirm rejection" })).toBeFocused();
  await expectAxeClean(page);
  await page.keyboard.press("Escape");
  await trigger.focus();

  await page.keyboard.press("Enter");
  dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(FIRST_ID);
  await expect(dialog).toContainText("reviewed immutable binding");
  await dialog.getByRole("button", { name: "Approve create issue" }).click();
  await expect.poll(() => state.commandRequests.length).toBe(1);
  expect(JSON.parse(state.commandRequests[0].body ?? "{}")).toMatchObject({
    expected_version: 3,
    approval_id: "00000000-0000-4000-8000-000000000003",
    reason: "reviewed immutable binding",
  });
});

test("approval dialog passes automated accessibility checks", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/approvals");
  await openApproval(page);
  await page.getByLabel("Operator reason").fill("accessibility review");
  await page.getByRole("button", { name: "Approve create issue" }).click();
  await expectAxeClean(page);
});

test("approval conflict reloads authoritative state without losing the reason", async ({ page }) => {
  const state = scenario({ commandFault: "conflict" });
  await installApi(page, state);
  await login(page, "/approvals");
  await openApproval(page);
  await page.getByLabel("Operator reason").fill("keep this reason");
  await page.getByRole("button", { name: "Approve create issue" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Approve create issue" }).click();

  await expect(page.getByText(/approval changed on the server/i)).toBeVisible();
  await expectAxeClean(page);
  await expect(page.getByLabel("Operator reason")).toHaveValue("keep this reason");
  await expect.poll(() => state.reconstructionReads).toBeGreaterThanOrEqual(2);
  await expect(page.getByRole("button", { name: "Approve create issue" })).toBeVisible();
});

test("read failure has an accessible retry and recovers", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/operations");
  await expect(page.getByText(FIRST_ID)).toBeVisible();
  state.listError = 503;
  await openFilters(page);
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("heading", { name: "Unable to load operations" })).toBeVisible();
  await expectAxeClean(page);
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText(FIRST_ID)).toBeVisible();
});

for (const fault of ["500", "503", "malformed", "connection"] satisfies CommandFault[]) {
  test(`indeterminate ${fault} reloads before exposing stable-identity retry`, async ({ page }) => {
    const state = scenario({ commandFault: fault });
    await installApi(page, state);
    await login(page, `/operations/${MANUAL_ID}`);
    await submitDetailCommand(page, state);

    await expect(page.getByRole("button", { name: "Retry same request" })).toBeVisible();
    await expectAxeClean(page);
    expect(state.reconstructionReads).toBeGreaterThanOrEqual(2);
    await page.getByRole("button", { name: "Retry same request" }).click();
    await expect.poll(() => state.commandRequests.length).toBe(2);
    expect(state.commandRequests[1].body).toBe(state.commandRequests[0].body);
    expect(state.commandRequests[1].headers["idempotency-key"]).toBe(state.commandRequests[0].headers["idempotency-key"]);
    expect(state.commandRequests[1].headers["x-correlation-id"]).toBe(state.commandRequests[0].headers["x-correlation-id"]);
  });
}

test("command timeout is indeterminate and keeps the stable retry identity", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "one real timeout path is sufficient; transport faults run in every engine");
  test.setTimeout(50_000);
  const state = scenario({ commandFault: "timeout" });
  await installApi(page, state);
  await login(page, `/operations/${MANUAL_ID}`);
  await submitDetailCommand(page, state);
  await expect(page.getByRole("button", { name: "Retry same request" })).toBeVisible({ timeout: 35_000 });
  expect(state.reconstructionReads).toBeGreaterThanOrEqual(2);
  await expectAxeClean(page);
  await page.getByRole("button", { name: "Retry same request" }).click();
  await expect.poll(() => state.commandRequests.length).toBe(2);
  expect(state.commandRequests[1].body).toBe(state.commandRequests[0].body);
  expect(state.commandRequests[1].headers["idempotency-key"]).toBe(state.commandRequests[0].headers["idempotency-key"]);
  expect(state.commandRequests[1].headers["x-correlation-id"]).toBe(state.commandRequests[0].headers["x-correlation-id"]);
});

for (const fault of ["403", "422", "429"] satisfies CommandFault[]) {
  test(`command ${fault} outcome is distinct and accessible`, async ({ page }) => {
    const state = scenario({ commandFault: fault });
    await installApi(page, state);
    await login(page, `/operations/${MANUAL_ID}`);
    await submitDetailCommand(page, state);
    await expect(page.getByRole("alert")).toContainText(fault === "403" ? "forbidden" : fault === "422" ? "validation error" : "rate limited");
    await expectAxeClean(page);
  });
}

test("mobile drawer traps focus, restores it, and route changes reset document scroll", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page);
  for (const width of [768, 320]) {
    await page.setViewportSize({ width, height: 800 });
    const menu = page.getByRole("button", { name: "Open navigation" });
    await expectTouchTarget(menu);
    await menu.click();
    const overviewLink = page.getByRole("link", { name: "Overview", exact: true });
    await expect(overviewLink).toBeFocused();
    await expectTouchTarget(overviewLink);
    await expectTouchTarget(page.getByRole("button", { name: "Close navigation" }));
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("link", { name: "Recovery", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Overview", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toBeFocused();
  }
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await navigateInSession(page, "/approvals");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
});

test("direct entry, refresh, Back, Forward, and not-found routing remain accessible", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/operations");
  await page.getByRole("link", { name: "Approvals", exact: true }).click();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Operations", level: 1 })).toBeFocused();
  await page.goForward();
  await expect(page.getByRole("heading", { name: "Approvals", level: 1 })).toBeFocused();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in to Stateback" })).toBeFocused();
  await login(page, "/missing-route");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expectAxeClean(page);
});

test("a response from the previous logged-out session cannot repopulate operator data", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/operations");
  await expect(page.getByText(FIRST_ID)).toBeVisible();

  let release!: () => void;
  state.listGate = new Promise<void>((resolve) => { release = resolve; });
  const requestCount = state.listRequests;
  await openFilters(page);
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect.poll(() => state.listRequests).toBe(requestCount + 1);
  await page.getByRole("button", { name: "Log out" }).click();
  release();
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByRole("heading", { name: "Sign in to Stateback" })).toBeFocused();
  await expect(page.getByText(FIRST_ID)).toHaveCount(0);
});

test("compensation retry requires explicit confirmation and exact context", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, "/recovery");
  await page.getByRole("button", { name: new RegExp(COMPENSATION_ID) }).click();
  await page.getByRole("button", { name: "Escalate compensation" }).click();
  await page.getByRole("dialog").getByLabel("Operator reason").fill("escalation review");
  await expectAxeClean(page);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Retry compensation" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(COMPENSATION_ID);
  await expect(dialog).toContainText(/BEST_EFFORT/);
  await dialog.getByLabel("Operator reason").fill("provider checked before retry");
  await expectAxeClean(page);
  await dialog.getByRole("button", { name: "Retry compensation" }).click();
  await expect.poll(() => state.commandRequests.length).toBe(1);
});

test("start-compensation confirmation is accessible and contract-bound", async ({ page }) => {
  const state = scenario();
  await installApi(page, state);
  await login(page, `/operations/${START_COMPENSATION_ID}`);
  await page.getByRole("button", { name: "Start compensation" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(START_COMPENSATION_ID);
  await dialog.getByLabel("Operator reason").fill("confirmed recovery boundary");
  await expectAxeClean(page);
});

test("visual evidence covers premium operator states at required viewports", async ({ page }, testInfo) => {
  test.skip(process.env.STATEBACK_VISUAL_EVIDENCE !== "1", "Visual evidence is captured deliberately.");
  const state = scenario();
  await installApi(page, state);
  const viewports = [
    { width: 1440, height: 900 },
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ];
  async function capture(name: string) {
    const body = await page.screenshot();
    await testInfo.attach(name, { body, contentType: "image/png" });
  }

  for (const viewport of viewports) {
    const suffix = `${viewport.width}x${viewport.height}`;
    await page.setViewportSize(viewport);
    await page.goto("/");
    if (await page.getByRole("button", { name: "Log out" }).isVisible()) await page.getByRole("button", { name: "Log out" }).click();
    await expect(page.getByRole("heading", { name: "Sign in to Stateback" })).toBeVisible();
    await capture(`access-${suffix}`);
    await page.getByLabel("Access token").fill("browser-test-token");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
    await capture(`overview-${suffix}`);

    await navigateInSession(page, "/operations");
    await expect(page.getByRole("heading", { name: "Operations", level: 1 })).toBeVisible();
    await expect(page.getByText(FIRST_ID, { exact: true })).toBeVisible();
    await capture(`operations-${suffix}`);
    await navigateInSession(page, `/operations/${SECOND_ID}`);
    await expect(page.getByRole("heading", { name: "Outcome unknown" })).toBeVisible();
    await capture(`unknown-detail-${suffix}`);
    await navigateInSession(page, `/operations/${START_COMPENSATION_ID}`);
    await expect(page.getByRole("button", { name: "Start compensation" })).toBeVisible();
    await capture(`successful-detail-${suffix}`);

    await navigateInSession(page, "/approvals");
    await openApproval(page);
    await page.evaluate(() => window.getSelection()?.removeAllRanges());
    await capture(`approval-review-${suffix}`);
    await navigateInSession(page, "/providers");
    await expect(page.getByRole("heading", { name: "Providers", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "GitHub" })).toBeVisible();
    await capture(`providers-${suffix}`);
    await navigateInSession(page, "/recovery");
    await expect(page.getByRole("heading", { name: "Recovery", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Compensation failed" })).toBeVisible();
    await capture(`recovery-${suffix}`);

    await navigateInSession(page, `/operations/${MANUAL_ID}`);
    await page.getByRole("button", { name: "Request verification" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await capture(`dialog-${suffix}`);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Search" }).click();
    const palette = page.getByRole("dialog", { name: "Command palette" });
    await expect(palette).toBeVisible();
    await expect(palette).toHaveCSS("opacity", "1");
    await page.waitForTimeout(250);
    await capture(`command-palette-${suffix}`);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Log out" }).click();
  }
});

test("all routes and supported viewport sizes retain essential operator data", async ({ page }, testInfo) => {
  const state = scenario();
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (value: string) => { Reflect.set(window, "__copiedValue", value); } },
    });
  });
  await installApi(page, state);
  await login(page);
  await expectAxeClean(page);
  if (process.env.STATEBACK_VISUAL_EVIDENCE === "1") {
    await page.setViewportSize({ width: 1440, height: 900 });
  }

  const routes = [
    ["Overview", "Overview"],
    ["Operations", "Operations"],
    ["Approvals", "Approvals"],
    ["Providers", "Providers"],
    ["Recovery", "Recovery"],
  ] as const;
  for (const [link, heading] of routes) {
    await page.getByRole("link", { name: link, exact: true }).click();
    await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
    await expectAxeClean(page);
    if (process.env.STATEBACK_VISUAL_EVIDENCE === "1") {
      const body = await page.screenshot({ fullPage: true });
      await testInfo.attach(`route-${link.toLocaleLowerCase()}`, { body, contentType: "image/png" });
    }
  }
  await page.getByRole("link", { name: "Operations", exact: true }).click();
  await page.getByRole("link", { name: /create issue/i }).click();
  await expect(page.getByRole("heading", { name: "Create issue with GitHub", level: 1 })).toBeVisible();
  await page.getByRole("navigation", { name: "Operation detail sections" }).getByRole("link", { name: "Audit" }).click();
  await expect(page).toHaveURL(/#audit-heading$/);
  await expectAxeClean(page);
  if (process.env.STATEBACK_VISUAL_EVIDENCE === "1") {
    const body = await page.screenshot({ fullPage: true });
    await testInfo.attach("operation-detail", { body, contentType: "image/png" });
  }

  for (const { width, height } of [
    { width: 1440, height: 900 },
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
    { width: 320, height: 568 },
  ]) {
    await page.setViewportSize({ width, height });
    await navigateInSession(page, "/operations");
    const row = page.locator(".operation-table tbody tr").first();
    await expect(row.getByText(FIRST_ID)).toBeVisible();
    await expect(row.getByText("Outcome unknown", { exact: true })).toBeVisible();
    await expect(row.getByRole("link", { name: /create issue/i })).toBeVisible();
    await expect(row.locator("time")).toHaveAttribute("title", "2026-08-20T12:00:00.000Z UTC");
    await expect(row.getByRole("button", { name: new RegExp(`Copy operation ID ${FIRST_ID}`) })).toBeVisible();
    if (width <= 390) {
      for (const cell of await row.locator("td").all()) await expectInsideViewport(cell, page, false);
      const copyId = row.getByRole("button", { name: new RegExp(`Copy operation ID ${FIRST_ID}`) });
      await expectTouchTarget(copyId);
      await expectTouchTarget(page.getByRole("button", { name: "Filters" }));
      await expectTouchTarget(page.getByRole("button", { name: "Open operation" }));
      await expectTouchTarget(page.getByRole("button", { name: "Search" }));
      await copyId.click();
      await expect(row.getByRole("status")).toHaveText("operation ID copied");
      expect(await page.evaluate(() => Reflect.get(window, "__copiedValue"))).toBe(FIRST_ID);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (process.env.STATEBACK_VISUAL_EVIDENCE === "1") {
      const body = await page.screenshot({ fullPage: true });
      await testInfo.attach(`operations-${width}`, { body, contentType: "image/png" });
    }
  }

  await page.setViewportSize({ width: 768, height: 1024 });
  await navigateInSession(page, "/operations");
  await openFilters(page);
  const stateSelect = page.locator(".operation-filters select");
  const providerInput = page.locator(".operation-filters input").first();
  await expectTouchTarget(stateSelect);
  await expectTouchTarget(providerInput);
  await providerInput.fill("github");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expectTouchTarget(page.getByRole("button", { name: "Remove provider github filter" }));
  await navigateInSession(page, `/operations/${MANUAL_ID}`);
  await expectTouchTarget(page.getByRole("navigation", { name: "Operation detail sections" }).getByRole("link", { name: "Lifecycle" }));
  await page.getByRole("button", { name: "Search" }).click();
  await expectTouchTarget(page.getByLabel("Search commands"));
  await page.keyboard.press("Escape");

  for (const { width, height } of [{ width: 390, height: 844 }, { width: 320, height: 568 }]) {
    await page.setViewportSize({ width, height });
    await navigateInSession(page, `/operations/${MANUAL_ID}`);
    await expect(page.getByRole("heading", { name: "Create issue with GitHub", level: 1 })).toBeVisible();
    await expectInsideViewport(page.locator(".operation-detail__critical-state"), page);
    await expectInsideViewport(page.getByText("Technical details"), page);
    await expectInsideViewport(page.getByRole("button", { name: "Request verification" }), page);
    await page.getByRole("button", { name: "Request verification" }).click();
    await page.getByLabel("Operator reason").fill("mobile command review");
    await expectInsideViewport(page.getByRole("dialog"), page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expectAxeClean(page);
    await page.keyboard.press("Escape");
  }

  await page.setViewportSize({ width: 720, height: 512 });
  await navigateInSession(page, "/operations");
  await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
  await expect(page.getByRole("heading", { name: "Operations", level: 1 })).toBeVisible();
  await expect(page.getByText(FIRST_ID)).toBeVisible();
  await expect(page.getByRole("button", { name: new RegExp(`Copy operation ID ${FIRST_ID}`) })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
