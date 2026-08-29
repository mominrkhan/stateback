import { useCallback, useEffect, useRef, useState } from "react";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { OperatorOverview } from "../../api/types";
import { CopyCommand } from "../../components/CopyCommand";
import { DefensiveState } from "../../components/DefensiveState";
import { actionLabel, effectIdentifier, providerLabel } from "../../presentation/labels";

const DEFAULT_CREATE_ABORT = () => new AbortController();
const DEFAULT_RELEASE_ABORT = () => undefined;

export function ProvidersPage({ client, createAbortController = DEFAULT_CREATE_ABORT, releaseAbortController = DEFAULT_RELEASE_ABORT }: { client: OperatorClient; createAbortController?: () => AbortController; releaseAbortController?: (controller: AbortController) => void }) {
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
      setError(cause instanceof Error ? cause.message : "Unable to load providers");
    } finally {
      releaseAbortController(controller);
      if (request.current === controller) request.current = null;
    }
  }, [client, createAbortController, releaseAbortController]);
  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);

  return <section aria-labelledby="providers-heading" className="providers-page"><header className="page-header"><p className="eyebrow">PROVIDER CONFIGURATION</p><h1 id="providers-heading" data-page-heading tabIndex={-1}>Providers</h1><p>Inspect the provider capabilities available to protected operations.</p></header>{!overview && !error ? <DefensiveState kind="loading" title="Loading providers" /> : error ? <DefensiveState kind="error" title="Could not load providers" onRetry={() => void load()}><p>{error}</p></DefensiveState> : overview?.providers.length === 0 ? <DefensiveState kind="empty" title="No providers are available" /> : overview?.providers.map((provider) => <article className="provider-card" key={provider.provider}><header><div><p className="eyebrow">PROVIDER</p><h2>{providerLabel(provider.provider)}</h2></div><span className={`configuration-status configuration-status--${provider.configured ? "configured" : "missing"}`}><span aria-hidden="true">{provider.configured ? "✓" : "–"}</span> {provider.configured ? "Configured" : "Not configured"}</span></header><div><h3>Supported effects</h3><ul>{provider.supported_effects.map((effect) => <li key={effectIdentifier(effect)}><strong>{actionLabel(effect)}</strong><code>{effectIdentifier(effect)}</code></li>)}</ul></div>{provider.configured ? <p>{providerLabel(provider.provider)} credentials are loaded only by provider-executing workers. Credential material is never exposed here.</p> : provider.provider === "github" ? <div className="provider-setup"><p>Connect GitHub from your terminal:</p><CopyCommand command="stateback connect github" /><p>Restart <code>stateback dev</code> after changing provider configuration.</p></div> : <p>This provider is not configured.</p>}</article>)}</section>;
}
