export type AppRoute =
  | { name: "root" }
  | { name: "operations"; search: string }
  | { name: "operation-detail"; operationId: string }
  | { name: "approvals" }
  | { name: "recovery" }
  | { name: "not-found" };

const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;

export function decodeOperationId(segment: string): string | null {
  if (!segment) return null;

  let decoded: string;
  try {
    decoded = decodeURIComponent(segment);
  } catch {
    return null;
  }

  if (
    decoded.length === 0
    || CONTROL_CHARACTERS.test(decoded)
    || decoded.includes("/")
  ) {
    return null;
  }
  return decoded;
}

export function parseRoute(location: Pick<Location, "pathname" | "search">): AppRoute {
  const { pathname, search } = location;
  if (pathname === "/") return { name: "root" };
  if (pathname === "/operations") return { name: "operations", search };
  if (pathname === "/approvals") return { name: "approvals" };
  if (pathname === "/recovery") return { name: "recovery" };

  const match = /^\/operations\/([^/]*)$/.exec(pathname);
  if (match) {
    const operationId = decodeOperationId(match[1]);
    if (operationId !== null) return { name: "operation-detail", operationId };
  }
  return { name: "not-found" };
}

export function routeKey(route: AppRoute): string {
  switch (route.name) {
    case "operations":
      return `/operations${route.search}`;
    case "operation-detail":
      return `/operations/${encodeURIComponent(route.operationId)}`;
    case "approvals":
      return "/approvals";
    case "recovery":
      return "/recovery";
    case "root":
      return "/";
    case "not-found":
      return "not-found";
  }
}
