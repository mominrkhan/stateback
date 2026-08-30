import { describe, expect, test } from "vitest";

import { actionLabel, providerLabel } from "./labels";

describe("GitHub v0.1 presentation coverage", () => {
  test.each([
    ["create_issue", "Create issue"],
    ["create_issue_comment", "Comment on issue"],
    ["add_label", "Add label"],
    ["create_pull_request", "Create pull request"],
    ["merge_pull_request", "Merge pull request"],
  ])("labels %s", (action, label) => {
    expect(actionLabel({ provider: "github", action, version: "v1" })).toBe(label);
    expect(providerLabel("github")).toBe("GitHub");
  });
});
