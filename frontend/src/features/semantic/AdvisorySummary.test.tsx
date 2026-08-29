import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { OperatorClient } from "../../api/client";
import { parseOperationPage, parseSemanticSummary } from "../../api/parsers";
import type { Operation, SemanticSummary } from "../../api/types";
import listFixture from "../../test/contract-fixtures/operation-list-v1.json";
import unavailableFixture from "../../test/contract-fixtures/semantic-unavailable-v1.json";
import { AdvisorySummary } from "./AdvisorySummary";

function operation(version = 2, id = "00000000-0000-4000-8000-000000000001"): Operation { const base = parseOperationPage(listFixture).items[0]; return { ...base, version, operation_id: id }; }
function semantic(overrides: Partial<SemanticSummary> = {}): SemanticSummary { return { ...parseSemanticSummary(unavailableFixture), ...overrides }; }
function client(summary: (id: string, signal?: AbortSignal) => Promise<SemanticSummary>): OperatorClient { return { overview: vi.fn(), list: vi.fn(), reconstruct: vi.fn(), command: vi.fn(), semanticSummary: vi.fn(summary) }; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }

describe("AdvisorySummary", () => {
  it("is explicitly requested and always identifies advisory non-authority", async () => {
    const api = client(async () => semantic()); render(<AdvisorySummary client={api} operation={operation()} />);
    expect(screen.getByText("Advisory")).toBeVisible(); expect(screen.getByText(/Non-authoritative/)).toBeVisible(); expect(api.semanticSummary).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Generate advisory summary" }));
    await screen.findByText(/Semantic assistance unavailable/); expect(api.semanticSummary).toHaveBeenCalledOnce();
  });

  it("renders available content with provenance and exact summarized bounds", async () => {
    const available = semantic({ status: "AVAILABLE", summary: "Audit history remains unresolved.", confidence: 0.8, key_events: [{ sequence: 1, description: "Verification started" }], unresolved_uncertainties: ["External effect remains unknown"], summarized_through_sequence: 1, provenance: { provider: "ollama", model: "local-model", prompt_version: "audit-summary-v1", output_schema_version: "v1" }, reason_code: "semantic_summary_available" });
    render(<AdvisorySummary client={client(async () => available)} operation={operation()} />); fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText("Audit history remains unresolved.")).toBeVisible(); expect(screen.getByText("ollama")).toBeVisible(); expect(screen.getByText("local-model")).toBeVisible();
    expect(screen.getByText("audit-summary-v1")).toBeVisible(); expect(screen.getByText("Sequence 1: Verification started")).toBeVisible();
  });

  it("rejects a mismatched summarized operation version", async () => {
    render(<AdvisorySummary client={client(async () => semantic({ summarized_operation_version: 1 }))} operation={operation(2)} />); fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/different operation version/)).toBeVisible(); expect(screen.queryByRole("button", { name: /approve|verify|compensate/i })).not.toBeInTheDocument();
  });

  it.each(["ABSTAINED", "UNAVAILABLE", "INVALID"] as const)("isolates %s without changing authoritative UI", async (status) => {
    render(<AdvisorySummary client={client(async () => semantic({ status, reason_code: `fixture_${status.toLowerCase()}` }))} operation={operation()} />); fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(new RegExp(`Semantic assistance ${status.toLowerCase()}`))).toHaveTextContent("Authoritative operation data is unchanged");
  });

  it("aborts and ignores a late response after operation/version switch", async () => {
    const first = deferred<SemanticSummary>(); let firstSignal: AbortSignal | undefined;
    const api = client(async (_id, signal) => { firstSignal = signal; return first.promise; });
    const view = render(<AdvisorySummary client={api} operation={operation(2)} />); fireEvent.click(screen.getByRole("button"));
    view.rerender(<AdvisorySummary client={api} operation={operation(3, "00000000-0000-4000-8000-000000000002")} />);
    expect(firstSignal?.aborted).toBe(true); first.resolve(semantic({ status: "AVAILABLE", summary: "Late stale text", confidence: 0.9, summarized_operation_version: 2 }));
    await waitFor(() => expect(screen.queryByText("Late stale text")).not.toBeInTheDocument()); expect(screen.getByText(/Generated only when requested/)).toBeVisible();
  });
});
