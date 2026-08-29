import { useEffect, useMemo } from "react";

import { createOperatorClient } from "../api/client";
import { AccessGate } from "../auth/AccessGate";
import { useAuthSession } from "../auth/AuthSession";
import { AppShell } from "../components/AppShell";
import { ApprovalsPage } from "../features/approvals/ApprovalsPage";
import { sessionCommandAttempts } from "../features/commands/attemptRegistry";
import { OperationsPage } from "../features/operations/OperationsPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { ProvidersPage } from "../features/providers/ProvidersPage";
import { RecoveryPage } from "../features/recovery/RecoveryPage";
import { useNavigation } from "./navigation";
import { routeKey, type AppRoute } from "./routes";
import { OperationDetailRoute } from "./OperationDetailRoute";
import "../design/global.css";

function PageHeading({ children }: { children: string }) {
  return <h1 data-page-heading tabIndex={-1}>{children}</h1>;
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
      return <OperationDetailRoute client={client} operationId={route.operationId} session={session} />;
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

  return (
    <AppShell
      key={session.sessionGeneration}
      currentPath={routeKey(navigation.route)}
      onNavigate={navigation.navigate}
      onLogout={() => session.clearSession("logout")}
    >
      <RouteContent route={navigation.route} navigate={navigation.navigate} />
    </AppShell>
  );
}
