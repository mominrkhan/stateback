import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { createOperatorClient } from "../api/client";
import { AccessGate } from "../auth/AccessGate";
import { useAuthSession } from "../auth/AuthSession";
import { AppShell } from "../components/AppShell";
import { Skeleton } from "../components/Skeleton";
import { sessionCommandAttempts } from "../features/commands/attemptRegistry";
import { useNavigation } from "./navigation";
import { routeKey, type AppRoute } from "./routes";
import "../design/global.css";

const OverviewPage = lazy(() => import("../features/overview/OverviewPage").then((module) => ({ default: module.OverviewPage })));
const OperationsPage = lazy(() => import("../features/operations/OperationsPage").then((module) => ({ default: module.OperationsPage })));
const OperationDetailRoute = lazy(() => import("./OperationDetailRoute").then((module) => ({ default: module.OperationDetailRoute })));
const ApprovalsPage = lazy(() => import("../features/approvals/ApprovalsPage").then((module) => ({ default: module.ApprovalsPage })));
const ProvidersPage = lazy(() => import("../features/providers/ProvidersPage").then((module) => ({ default: module.ProvidersPage })));
const RecoveryPage = lazy(() => import("../features/recovery/RecoveryPage").then((module) => ({ default: module.RecoveryPage })));

function PageHeading({ children }: { children: string }) {
  return <h1 data-page-heading tabIndex={-1}>{children}</h1>;
}

function RouteFocus({ focusKey, children }: { focusKey: string; children: ReactNode }) {
  useLayoutEffect(() => {
    document.querySelector<HTMLElement>("[data-page-heading]")?.focus({ preventScroll: true });
  }, [focusKey]);
  return children;
}

function RouteLoading({ route }: { route: AppRoute }) {
  const loadingHeading = useRef<HTMLHeadingElement>(null);
  const heading = route.name === "root" ? "Overview"
    : route.name === "operation-detail" || route.name === "operations" ? "Operations"
      : route.name === "approvals" ? "Approvals"
        : route.name === "providers" ? "Providers"
          : route.name === "recovery" ? "Recovery"
            : "Page not found";
  useLayoutEffect(() => { loadingHeading.current?.focus({ preventScroll: true }); }, [heading]);
  return <section aria-busy="true"><h1 ref={loadingHeading} className="visually-hidden" tabIndex={-1}>{heading}</h1><Skeleton label={`Loading ${heading}`} /></section>;
}

function RouteContent({ route, navigate }: { route: AppRoute; navigate: (href: string) => void }) {
  const session = useAuthSession();
  const client = useMemo(() => createOperatorClient({
    token: session.getAccessToken,
    onUnauthorized: () => session.clearSession("unauthorized"),
    createAbortController: session.createAbortController,
    releaseAbortController: session.releaseAbortController,
  }), [session.sessionGeneration]);

  switch (route.name) {
    case "root":
      return <OverviewPage client={client} navigate={navigate} createAbortController={session.createAbortController} releaseAbortController={session.releaseAbortController} />;
    case "operations":
      return <OperationsPage client={client} search={route.name === "operations" ? route.search : ""} navigate={navigate} createAbortController={session.createAbortController} releaseAbortController={session.releaseAbortController} />;
    case "operation-detail":
      return <OperationDetailRoute client={client} operationId={route.operationId} session={session} navigate={navigate} />;
    case "approvals":
      return <ApprovalsPage client={client} createAbortController={session.createAbortController} releaseAbortController={session.releaseAbortController} />;
    case "providers":
      return <ProvidersPage client={client} createAbortController={session.createAbortController} releaseAbortController={session.releaseAbortController} />;
    case "recovery":
      return <RecoveryPage client={client} attemptRegistry={sessionCommandAttempts} createAbortController={session.createAbortController} releaseAbortController={session.releaseAbortController} sessionGeneration={session.sessionGeneration} isCurrentGeneration={session.isCurrentGeneration} />;
    case "not-found":
      return <><PageHeading>Page not found</PageHeading><p>This operator route is not supported.</p></>;
  }
}

export function App() {
  const session = useAuthSession();
  const navigation = useNavigation(session.authenticated);

  useEffect(() => {
    if (!session.authenticated) sessionCommandAttempts.clear();
  }, [session.authenticated, session.sessionGeneration]);

  if (!session.authenticated) return <AccessGate />;

  return <AuthenticatedApp key={session.sessionGeneration} route={navigation.route} navigate={navigation.navigate} />;
}

function AuthenticatedApp({ route, navigate }: { route: AppRoute; navigate: (href: string) => void }) {
  const session = useAuthSession();
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 15_000, refetchOnWindowFocus: false }, mutations: { retry: false } } }));
  const currentRouteKey = routeKey(route);
  return <QueryClientProvider client={queryClient}><AppShell currentPath={currentRouteKey} onNavigate={navigate} onLogout={() => { queryClient.clear(); session.clearSession("logout"); }}><Suspense fallback={<RouteLoading route={route} />}><RouteFocus focusKey={currentRouteKey}><RouteContent route={route} navigate={navigate} /></RouteFocus></Suspense></AppShell></QueryClientProvider>;
}
