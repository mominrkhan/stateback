import errorFixture from "../test/contract-fixtures/error-v1.json";
import listFixture from "../test/contract-fixtures/operation-list-v1.json";
import reconstructionFixture from "../test/contract-fixtures/reconstruction-empty-verifications-v1.json";
import verificationFixture from "../test/contract-fixtures/reconstruction-verification-v1.json";
import semanticFixture from "../test/contract-fixtures/semantic-unavailable-v1.json";
import { ParseFailure } from "./errors";
import { parseApiError, parseOperationPage, parseReconstruction, parseSemanticSummary } from "./parsers";

describe("contract parsers", () => {
  it("parses authoritative list, reconstruction, semantic, and error fixtures", () => {
    expect(parseOperationPage(listFixture).next_cursor).toBe("fixture-cursor");
    expect(parseReconstruction(reconstructionFixture).operation.intent.effect.action).toBe("create_issue");
    expect(parseSemanticSummary(semanticFixture).status).toBe("UNAVAILABLE");
    expect(parseApiError(errorFixture, 409).code).toBe("stale_version");
  });

  it("preserves an unknown future operation state", () => {
    const fixture = structuredClone(listFixture); fixture.items[0].state = "FUTURE_STATE";
    expect(parseOperationPage(fixture).items[0].state).toBe("FUTURE_STATE");
  });

  it.each([
    ["contract version", (value: Record<string, unknown>) => { value.contract_version = "v2"; }, "list.contract_version"],
    ["nested effect", (value: Record<string, unknown>) => { const items = value.items as Array<Record<string, unknown>>; const intent = items[0].intent as Record<string, unknown>; intent.effect = null; }, "list.items[0].intent.effect"],
    ["operation version", (value: Record<string, unknown>) => { const items = value.items as Array<Record<string, unknown>>; items[0].version = 0; }, "list.items[0].version"],
    ["operation timestamp", (value: Record<string, unknown>) => { const items = value.items as Array<Record<string, unknown>>; items[0].created_at = "not-a-time"; }, "list.items[0].created_at"],
    ["cursor type", (value: Record<string, unknown>) => { value.next_cursor = 4; }, "list.next_cursor"],
  ])("rejects malformed %s with a field path", (_label, mutate, field) => {
    const fixture: Record<string, unknown> = structuredClone(listFixture); mutate(fixture);
    expect(() => parseOperationPage(fixture)).toThrow(expect.objectContaining<Partial<ParseFailure>>({ field }));
  });

  it("parses the backend verification request/result history shape", () => {
    const parsed = parseReconstruction(verificationFixture);
    expect(parsed.verifications).toHaveLength(1);
    expect(parsed.verifications[0].result?.outcome).toBe("APPLIED");
  });

  it("enforces semantic content limits and status coupling", () => {
    const fixture: Record<string, unknown> = structuredClone(semanticFixture); fixture.summary = "not allowed";
    expect(() => parseSemanticSummary(fixture)).toThrow("semantic: status/content mismatch");
  });
});
