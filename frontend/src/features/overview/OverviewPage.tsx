import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { OperatorOverview } from "../../api/types";
import { CopyCommand } from "../../components/CopyCommand";
import { DefensiveState } from "../../components/DefensiveState";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";
import { actionLabel, providerLabel, requesterLabel } from "../../presentation/labels";

const DEFAULT_CREATE_ABORT = () => new AbortController();
const DEFAULT_RELEASE_ABORT = () => undefined;

export interface OverviewPageProps {
  client: OperatorClient;
  navigate: (href: string) => void;
  createAbortController?: () => AbortController;
  releaseAbortController?: (controller: AbortController) => void;
}

export function OverviewPage({ client, navigate, createAbortController = DEFAULT_CREATE_ABORT, releaseAbortController = DEFAULT_RELEASE_ABORT }: OverviewPageProps) {
  const request = useRef<AbortController | null>(null);
  const [overview, setOverview] = useState<OperatorOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = createAbortController();
    request.current = controller;
    setError(null);
    try {
      const result = await client.overview(controller.signal);
      if (!controller.signal.aborted) setOverview(result);
    } catch (cause) {
      if (controller.signal.aborted || cause instanceof ApiError && cause.status === 401) return;
      setError(cause instanceof Error ? cause.message : "Unable to load overview");
    } finally {
      releaseAbortController(controller);
      if (request.current === controller) request.current = null;
    }
  }, [client, createAbortController, releaseAbortController]);

  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load]);

  function follow(event: MouseEvent<HTMLAnchorElement>, href: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(href);
  }

  const pageHeader = <header className="page-header"><p className="eyebrow">OPERATOR OVERVIEW</p><h1 id="overview-heading" data-page-heading tabIndex={-1}>Overview</h1><p>Monitor protected agent actions and resolve anything that needs attention.</p></header>;
  if (!overview && !error) return <section aria-labelledby="overview-heading" className="overview-page">{pageHeader}<DefensiveState kind="loading" title="Loading overview" /></section>;
  if (error) return <section aria-labelledby="overview-heading" className="overview-page">{pageHeader}<DefensiveState kind="error" title="Could not load overview" onRetry={() => void load()}><p>{error}</p></DefensiveState></section>;
  if (!overview) return null;

  const github = overview.providers.find((provider) => provider.provider === "github");
  const attention = [
    { label: "Awaiting approval", count: overview.attention.awaiting_approval, symbol: "!", href: "/approvals" },
    { label: "Outcome unknown", count: overview.attention.unknown, symbol: "?", href: "/operations?state=UNKNOWN&limit=50" },
    { label: "Manual intervention", count: overview.attention.manual_intervention, symbol: "!", href: "/operations?state=MANUAL_INTERVENTION&limit=50" },
    { label: "Compensation issue", count: overview.attention.compensation_issues, symbol: "?", href: "/recovery" },
  ];
  const attentionTotal = attention.reduce((total, item) => total + item.count, 0);

  return (
    <section aria-labelledby="overview-heading" className="overview-page">
      {pageHeader}

      {overview.total_operations === 0 && (
        <section className="onboarding" aria-labelledby="welcome-heading">
          <div><p className="eyebrow">READY FOR FIRST USE</p><h2 id="welcome-heading">Welcome to Stateback</h2></div>
          <p>Stateback is running and ready to protect consequential agent actions.</p>
          <ol className="onboarding__steps">
            <li><strong>{github?.configured ? "GitHub configured" : "Connect GitHub"}</strong>{github?.configured ? <p>Credentials are configured for provider-executing workers.</p> : <CopyCommand command="stateback connect github" />}</li>
            <li><strong>Submit your first protected operation</strong><p>Use the API, Python SDK, or MCP interface described in the documentation.</p></li>
            <li><strong>Stateback preserves external truth</strong><p>Intent, policy, attempts, evidence, and uncertainty remain durable.</p></li>
          </ol>
          <aside className="unknown-explainer"><h3>Why UNKNOWN exists</h3><p>GitHub may complete an action even if Stateback never receives the response. Instead of blindly retrying and risking a duplicate, Stateback records the outcome as UNKNOWN and verifies external reality before deciding what is safe.</p></aside>
        </section>
      )}

      <section aria-labelledby="attention-heading">
        <div className="section-heading"><div><p className="eyebrow">PRIORITY</p><h2 id="attention-heading">Needs attention</h2></div>{attentionTotal === 0 && <p className="clear-state">✓ No operations need attention</p>}</div>
        <div className="attention-grid">
          {attention.map((item) => <a key={item.label} href={item.href} className="attention-card" onClick={(event) => follow(event, item.href)}><span aria-hidden="true" className="attention-card__symbol">{item.symbol}</span><span><strong>{item.count}</strong><small>{item.label}</small></span></a>)}
        </div>
      </section>

      <div className="overview-grid">
        <section aria-labelledby="active-heading"><h2 id="active-heading">Active</h2><dl className="compact-counts"><div><dt>Executing</dt><dd>{overview.active.executing}</dd></div><div><dt>Verifying</dt><dd>{overview.active.verifying}</dd></div><div><dt>Compensating</dt><dd>{overview.active.compensating}</dd></div></dl></section>
        <section aria-labelledby="runtime-heading"><h2 id="runtime-heading">Runtime</h2><ul className="signal-list"><li><span aria-hidden="true">✓</span> API connected</li><li><span aria-hidden="true">✓</span> Database ready</li></ul></section>
      </div>

      <section aria-labelledby="recent-heading"><div className="section-heading"><h2 id="recent-heading">Recent activity</h2>{overview.recent_operations.length > 0 && <a href="/operations" onClick={(event) => follow(event, "/operations")}>View all operations</a>}</div>{overview.recent_operations.length === 0 ? <p className="detail-empty">No operations yet.</p> : <ul className="recent-operations">{overview.recent_operations.map((operation) => { const href = `/operations/${encodeURIComponent(operation.operation_id)}`; return <li key={operation.operation_id}><a href={href} onClick={(event) => follow(event, href)}><span><strong>{actionLabel(operation.intent.effect)}</strong><small>{providerLabel(operation.intent.effect.provider)} · {requesterLabel(operation.intent.requester)}</small></span><StateBadge state={operation.state} /><Timestamp value={operation.updated_at} /></a></li>; })}</ul>}</section>

      <section aria-labelledby="providers-summary-heading"><div className="section-heading"><h2 id="providers-summary-heading">Providers</h2><a href="/providers" onClick={(event) => follow(event, "/providers")}>View providers</a></div>{overview.providers.map((provider) => <div className="provider-summary" key={provider.provider}><div><strong>{providerLabel(provider.provider)}</strong><p>{provider.configured ? "Configured" : "Not configured"} · {provider.supported_effects.length} supported effect{provider.supported_effects.length === 1 ? "" : "s"}</p></div>{!provider.configured && provider.provider === "github" && <CopyCommand command="stateback connect github" />}</div>)}</section>
    </section>
  );
}
