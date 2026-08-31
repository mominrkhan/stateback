import { useQuery } from "@tanstack/react-query";
import { CircleCheck, GitBranch, LockKeyhole, PlugZap } from "lucide-react";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import { OperatorQueryBoundary } from "../../app/OperatorQueryBoundary";
import { CopyCommand } from "../../components/CopyCommand";
import { DefensiveState } from "../../components/DefensiveState";
import { actionLabel, effectIdentifier, providerLabel } from "../../presentation/labels";

interface ProvidersPageProps { client: OperatorClient; createAbortController?: () => AbortController; releaseAbortController?: (controller: AbortController) => void }

export function ProvidersPage({ client }: ProvidersPageProps) {
  return <OperatorQueryBoundary><ProvidersContent client={client} /></OperatorQueryBoundary>;
}

function ProvidersContent({ client }: Pick<ProvidersPageProps, "client">) {
  const query = useQuery({ queryKey: ["operator", "overview"], queryFn: ({ signal }) => client.overview(signal) });
  const overview = query.data;
  const error = query.error instanceof ApiError && query.error.status === 401 ? null : query.error instanceof Error ? query.error.message : query.error ? "Unable to load providers" : null;
  return (
    <section aria-labelledby="providers-heading" className="providers-page">
      <header className="page-header"><div><p className="eyebrow">PROVIDER CONFIGURATION</p><h1 id="providers-heading" data-page-heading tabIndex={-1}>Providers</h1><p>Provider capabilities available to protected operations, reported by Stateback.</p></div></header>
      {!overview && !error ? <DefensiveState kind="loading" title="Loading providers" /> : error ? <DefensiveState kind="error" title="Could not load providers" onRetry={() => void query.refetch()}><p>{error}</p></DefensiveState> : overview?.providers.length === 0 ? <DefensiveState kind="empty" title="No providers are available" /> : overview?.providers.map((provider) => (
        <article className="provider-card" key={provider.provider}>
          <header><div className="provider-card__identity"><span className="provider-card__icon">{provider.provider === "github" ? <GitBranch size={22} /> : <PlugZap size={22} />}</span><div><p className="eyebrow">PROVIDER</p><h2>{providerLabel(provider.provider)}</h2></div></div><span className={`configuration-status configuration-status--${provider.configured ? "configured" : "missing"}`}>{provider.configured ? <CircleCheck size={14} /> : <PlugZap size={14} />} {provider.configured ? "Configured" : "Not configured"}</span></header>
          <div className="provider-card__body"><section><h3>Supported actions</h3><ul>{provider.supported_effects.map((effect) => <li key={effectIdentifier(effect)}><span><CircleCheck size={14} aria-hidden="true" /><strong>{actionLabel(effect)}</strong></span><code>{effectIdentifier(effect)}</code></li>)}</ul></section><aside><LockKeyhole size={17} aria-hidden="true" /><p>Credentials are loaded only by provider-executing workers. Credential material is never exposed here.</p></aside></div>
          {!provider.configured && provider.provider === "github" ? <div className="provider-setup"><p>Connect GitHub from your terminal</p><CopyCommand command="stateback connect github" /><small>Restart <code>stateback dev</code> after changing provider configuration.</small></div> : null}
        </article>
      ))}
    </section>
  );
}
