import { useEffect, useRef, useState } from "react";

import type { OperatorClient } from "../../api/client";
import type { Operation, SemanticSummary } from "../../api/types";

type AdvisoryPhase = "idle" | "loading" | "available" | "abstained" | "unavailable" | "invalid" | "stale" | "error";

export interface AdvisorySummaryProps { client: OperatorClient; operation: Operation }

export function AdvisorySummary({ client, operation }: AdvisorySummaryProps) {
  const selection = `${operation.operation_id}\u0000${operation.version}`;
  const selectionRef = useRef(selection); selectionRef.current = selection;
  const generationRef = useRef(0);
  const requestRef = useRef<AbortController | null>(null);
  const [phase, setPhase] = useState<AdvisoryPhase>("idle");
  const [summary, setSummary] = useState<SemanticSummary | null>(null);

  useEffect(() => {
    generationRef.current += 1; requestRef.current?.abort(); requestRef.current = null;
    setPhase("idle"); setSummary(null);
    return () => requestRef.current?.abort();
  }, [selection]);

  async function requestSummary() {
    requestRef.current?.abort(); const controller = new AbortController(); requestRef.current = controller;
    const generation = ++generationRef.current; const requestedSelection = selection;
    setPhase("loading"); setSummary(null);
    try {
      const result = await client.semanticSummary(operation.operation_id, controller.signal);
      if (controller.signal.aborted || generationRef.current !== generation || selectionRef.current !== requestedSelection) return;
      if (result.summarized_operation_version !== operation.version) { setPhase("stale"); return; }
      setSummary(result);
      setPhase(result.status === "AVAILABLE" ? "available" : result.status === "ABSTAINED" ? "abstained" : result.status === "UNAVAILABLE" ? "unavailable" : "invalid");
    } catch {
      if (controller.signal.aborted || generationRef.current !== generation || selectionRef.current !== requestedSelection) return;
      setPhase("error");
    } finally {
      if (generationRef.current === generation) requestRef.current = null;
    }
  }

  return (
    <aside className="advisory-summary advisory-summary--inset advisory-summary--dashed" aria-labelledby="advisory-summary-heading">
      <header>
        <p className="advisory-summary__label">Advisory</p>
        <h2 id="advisory-summary-heading">Semantic audit summary</h2>
        <p className="advisory-summary__authority">Non-authoritative. Use durable evidence and audit history for decisions.</p>
      </header>
      <button className="primitive-button" type="button" onClick={() => void requestSummary()} disabled={phase === "loading"}>
        {phase === "loading" ? "Generating advisory summary…" : "Generate advisory summary"}
      </button>
      <div aria-live="polite" aria-busy={phase === "loading" || undefined}>
        {phase === "idle" && <p>Generated only when requested by an operator.</p>}
        {phase === "loading" && <p>Requesting advisory analysis…</p>}
        {phase === "stale" && <p>Summary rejected because it describes a different operation version.</p>}
        {phase === "error" && <p>Semantic assistance failed. Authoritative operation data remains available.</p>}
        {(phase === "abstained" || phase === "unavailable" || phase === "invalid") && summary && (
          <p>Semantic assistance {phase}: {summary.reason_code}. Authoritative operation data is unchanged.</p>
        )}
        {phase === "available" && summary && summary.summary && (
          <section className="advisory-summary__content">
            <p>{summary.summary}</p>
            {summary.key_events.length > 0 && <><h3>Key audit events</h3><ul>{summary.key_events.map((event) => <li key={`${event.sequence}-${event.description}`}>Sequence {event.sequence}: {event.description}</li>)}</ul></>}
            {summary.unresolved_uncertainties.length > 0 && <><h3>Unresolved uncertainties</h3><ul>{summary.unresolved_uncertainties.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></>}
          </section>
        )}
      </div>
      {summary && <dl className="advisory-summary__provenance">
        <div><dt>Provider</dt><dd>{summary.provenance.provider ?? "Not supplied"}</dd></div>
        <div><dt>Model</dt><dd>{summary.provenance.model ?? "Not supplied"}</dd></div>
        <div><dt>Prompt version</dt><dd>{summary.provenance.prompt_version}</dd></div>
        <div><dt>Summarized operation version</dt><dd>{summary.summarized_operation_version}</dd></div>
        <div><dt>Summarized through audit sequence</dt><dd>{summary.summarized_through_sequence}</dd></div>
      </dl>}
    </aside>
  );
}
