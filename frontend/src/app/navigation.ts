import { useCallback, useEffect, useLayoutEffect, useState } from "react";

import { parseRoute, routeKey, type AppRoute } from "./routes";

function currentRoute(): AppRoute {
  return parseRoute(window.location);
}

function focusRouteContent(): void {
  const main = document.getElementById("main-content");
  if (main) main.scrollTop = 0;
  window.scrollTo(0, 0);
  document.querySelector<HTMLElement>("[data-page-heading]")?.focus({ preventScroll: true });
}

export interface Navigation {
  route: AppRoute;
  navigate: (href: string, options?: { replace?: boolean }) => void;
}

export function useNavigation(enabled: boolean): Navigation {
  const [route, setRoute] = useState<AppRoute>(currentRoute);

  const readLocation = useCallback(() => {
    const next = currentRoute();
    if (enabled && next.name === "root") {
      window.history.replaceState(null, "", "/operations");
      setRoute({ name: "operations", search: "" });
      return;
    }
    setRoute(next);
  }, [enabled]);

  useEffect(() => {
    window.addEventListener("popstate", readLocation);
    readLocation();
    return () => window.removeEventListener("popstate", readLocation);
  }, [readLocation]);

  useLayoutEffect(() => {
    if (enabled) focusRouteContent();
  }, [enabled, routeKey(route)]);

  const navigate = useCallback((href: string, options?: { replace?: boolean }) => {
    const url = new URL(href, window.location.href);
    if (url.origin !== window.location.origin) return;
    window.history[options?.replace ? "replaceState" : "pushState"](null, "", `${url.pathname}${url.search}`);
    setRoute(currentRoute());
  }, []);

  return { route, navigate };
}
