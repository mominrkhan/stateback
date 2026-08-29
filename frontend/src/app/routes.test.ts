import { parseRoute } from "./routes";

function at(pathname: string, search = "") {
  return parseRoute({ pathname, search });
}

test("parses only the supported route union", () => {
  expect(at("/")).toEqual({ name: "root" });
  expect(at("/operations", "?state=UNKNOWN")).toEqual({ name: "operations", search: "?state=UNKNOWN" });
  expect(at("/approvals")).toEqual({ name: "approvals" });
  expect(at("/providers")).toEqual({ name: "providers" });
  expect(at("/recovery")).toEqual({ name: "recovery" });
  expect(at("/audit")).toEqual({ name: "not-found" });
});

test("accepts opaque operation IDs without assuming UUID syntax", () => {
  expect(at("/operations/provider%3Aopaque-1")).toEqual({
    name: "operation-detail",
    operationId: "provider:opaque-1",
  });
});

test.each([
  "/operations/",
  "/operations/%",
  "/operations/%2F",
  "/operations/a%0Ab",
  "/operations/a/b",
])("rejects structurally invalid operation route %s", (pathname) => {
  expect(at(pathname)).toEqual({ name: "not-found" });
});
