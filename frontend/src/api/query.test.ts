import { operationQuery } from "./query";

describe("operationQuery", () => {
  it("uses only accepted names and browser encoding", () => {
    expect(operationQuery({ state: "UNKNOWN", provider: "git hub", createdFrom: "2026-01-01T00:00:00Z", createdTo: "2026-01-02T00:00:00Z", cursor: "a+b/=", limit: 25 }))
      .toBe("?state=UNKNOWN&provider=git+hub&created_from=2026-01-01T00%3A00%3A00Z&created_to=2026-01-02T00%3A00%3A00Z&cursor=a%2Bb%2F%3D&limit=25");
  });
  it("omits absent values and validates limit", () => {
    expect(operationQuery()).toBe("");
    expect(() => operationQuery({ limit: 101 })).toThrow(RangeError);
  });
});
