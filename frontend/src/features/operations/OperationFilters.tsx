import { useEffect, useState, type FormEvent } from "react";
import { Popover } from "@base-ui/react/popover";
import { CircleHelp, ListFilter, ShieldAlert, X } from "lucide-react";

import { OPERATION_STATES } from "../../api/types";
import type { OperationFilters as ApiOperationFilters } from "../../api/query";
import { operationStateLabel } from "../../presentation/labels";

export interface OperationsFilterValues {
  state?: string;
  attention?: boolean;
  provider?: string;
  createdFrom?: string;
  createdTo?: string;
  limit: number;
}

export interface ParsedOperationsSearch {
  filters: OperationsFilterValues;
  invalid: boolean;
}

const DEFAULT_LIMIT = 50;

function validUtc(value: string): boolean {
  return value.endsWith("Z") && !Number.isNaN(new Date(value).valueOf());
}

export function parseOperationsSearch(search: string): ParsedOperationsSearch {
  const query = new URLSearchParams(search);
  const state = query.get("state");
  const attention = query.get("attention");
  const provider = query.get("provider");
  const createdFrom = query.get("created_from");
  const createdTo = query.get("created_to");
  const rawLimit = query.get("limit");
  const limit = rawLimit === null ? DEFAULT_LIMIT : Number(rawLimit);
  const invalid = (state !== null && !(OPERATION_STATES as readonly string[]).includes(state))
    || (attention !== null && attention !== "true")
    || (state !== null && attention !== null)
    || (provider !== null && (provider.length === 0 || provider.length > 100))
    || (createdFrom !== null && !validUtc(createdFrom))
    || (createdTo !== null && !validUtc(createdTo))
    || !Number.isInteger(limit) || limit < 1 || limit > 100;

  if (invalid) return { filters: { limit: DEFAULT_LIMIT }, invalid: true };
  return {
    filters: {
      ...(state === null ? {} : { state }),
      ...(attention === "true" ? { attention: true } : {}),
      ...(provider === null ? {} : { provider }),
      ...(createdFrom === null ? {} : { createdFrom }),
      ...(createdTo === null ? {} : { createdTo }),
      limit,
    },
    invalid: false,
  };
}

export function serializeOperationsFilters(filters: OperationsFilterValues): string {
  const query = new URLSearchParams();
  if (filters.state) query.set("state", filters.state);
  if (filters.attention) query.set("attention", "true");
  if (filters.provider) query.set("provider", filters.provider);
  if (filters.createdFrom) query.set("created_from", filters.createdFrom);
  if (filters.createdTo) query.set("created_to", filters.createdTo);
  query.set("limit", String(filters.limit));
  return `?${query.toString()}`;
}

export function toApiFilters(filters: OperationsFilterValues, cursor?: string): ApiOperationFilters {
  return { ...filters, ...(cursor === undefined ? {} : { cursor }) };
}

function toLocalInput(value: string | undefined): string {
  if (!value || !validUtc(value)) return "";
  return value.slice(0, 19);
}

function fromLocalInput(value: string): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(`${value.length === 16 ? `${value}:00` : value}.000Z`);
  return Number.isNaN(parsed.valueOf()) ? undefined : parsed.toISOString();
}

interface OperationFiltersProps {
  values: OperationsFilterValues;
  invalidSearch?: boolean;
  onApply: (filters: OperationsFilterValues) => void;
  onRemove: (key: "state" | "attention" | "provider" | "createdFrom" | "createdTo") => void;
  onClear: () => void;
}

export function OperationFilters({ values, invalidSearch = false, onApply, onRemove, onClear }: OperationFiltersProps) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [state, setState] = useState(values.attention ? "NEEDS_ATTENTION" : values.state ?? "");
  const [provider, setProvider] = useState(values.provider ?? "");
  const [createdFrom, setCreatedFrom] = useState(toLocalInput(values.createdFrom));
  const [createdTo, setCreatedTo] = useState(toLocalInput(values.createdTo));
  const [limit, setLimit] = useState(String(values.limit));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setState(values.attention ? "NEEDS_ATTENTION" : values.state ?? "");
    setProvider(values.provider ?? "");
    setCreatedFrom(toLocalInput(values.createdFrom));
    setCreatedTo(toLocalInput(values.createdTo));
    setLimit(String(values.limit));
  }, [values.attention, values.createdFrom, values.createdTo, values.limit, values.provider, values.state]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const numericLimit = Number(limit);
    const normalizedProvider = provider.trim();
    const lower = fromLocalInput(createdFrom);
    const upper = fromLocalInput(createdTo);
    if (!Number.isInteger(numericLimit) || numericLimit < 1 || numericLimit > 100) {
      setError("Limit must be a whole number from 1 to 100.");
      return;
    }
    if (normalizedProvider.length > 100) {
      setError("Provider must be at most 100 characters.");
      return;
    }
    if ((createdFrom && !lower) || (createdTo && !upper)) {
      setError("Created timestamps must be valid UTC values.");
      return;
    }
    if (lower && upper && lower > upper) {
      setError("Created from must be before or equal to created to.");
      return;
    }
    setError(null);
    setFiltersOpen(false);
    onApply({
      ...(state === "NEEDS_ATTENTION" ? { attention: true } : state ? { state } : {}),
      ...(normalizedProvider ? { provider: normalizedProvider } : {}),
      ...(lower ? { createdFrom: lower } : {}),
      ...(upper ? { createdTo: upper } : {}),
      limit: numericLimit,
    });
  }

  return (
    <div className="filter-toolbar" aria-label="Operation filters">
      {invalidSearch && <p role="alert">Unsupported operation filters were ignored.</p>}
      <div className="filter-toolbar__quick">
        <button type="button" className={`filter-chip${values.attention ? " filter-chip--active" : ""}`} onClick={() => onApply({ limit: values.limit, attention: true })}><ShieldAlert size={14} />Needs attention</button>
        <button type="button" className={`filter-chip${values.state === "UNKNOWN" ? " filter-chip--active" : ""}`} onClick={() => onApply({ limit: values.limit, state: "UNKNOWN" })}><CircleHelp size={14} />Unknown</button>
        <button type="button" className={`filter-chip${values.state === "AWAITING_APPROVAL" ? " filter-chip--active" : ""}`} onClick={() => onApply({ limit: values.limit, state: "AWAITING_APPROVAL" })}>Awaiting approval</button>
      </div>
      <Popover.Root open={filtersOpen} onOpenChange={setFiltersOpen}>
        <Popover.Trigger className="primitive-button"><ListFilter size={15} aria-hidden="true" /> Filters</Popover.Trigger>
        <Popover.Portal><Popover.Positioner sideOffset={8} align="end"><Popover.Popup className="filter-popover"><Popover.Arrow className="filter-popover__arrow" /><div className="filter-popover__header"><div><p className="eyebrow">DISPLAY CONTROLS</p><Popover.Title>Filter operations</Popover.Title></div><Popover.Close className="icon-button" aria-label="Close filters"><X size={16} /></Popover.Close></div><form className="operation-filters" onSubmit={submit}>
      {error && <p role="alert" id="operation-filter-error">{error}</p>}
      <label>
        State
        <select value={state} onChange={(event) => setState(event.currentTarget.value)}>
          <option value="">All states</option>
          <option value="NEEDS_ATTENTION">Needs attention</option>
          {OPERATION_STATES.map((value) => <option key={value} value={value}>{operationStateLabel(value)}</option>)}
        </select>
      </label>
      <label>
        Provider (exact)
        <input value={provider} maxLength={100} onChange={(event) => setProvider(event.currentTarget.value)} />
      </label>
      <label>
        Created from (UTC)
        <input type="datetime-local" step={1} value={createdFrom} onChange={(event) => setCreatedFrom(event.currentTarget.value)} />
      </label>
      <label>
        Created to (UTC, inclusive)
        <input type="datetime-local" step={1} value={createdTo} onChange={(event) => setCreatedTo(event.currentTarget.value)} />
      </label>
      <label>
        Results per page
        <input type="number" min={1} max={100} step={1} value={limit} onChange={(event) => setLimit(event.currentTarget.value)} />
      </label>
      <div className="operation-filters__actions">
        <button type="submit" className="primitive-button primitive-button--primary">Apply filters</button>
        <button type="button" className="primitive-button" onClick={() => { setFiltersOpen(false); onClear(); }}>Clear filters</button>
      </div>
        </form></Popover.Popup></Popover.Positioner></Popover.Portal>
      </Popover.Root>
      {(values.attention || values.state || values.provider || values.createdFrom || values.createdTo) && <div className="active-filters"><span>Active:</span>{values.attention && <button type="button" aria-label="Remove Needs attention filter" onClick={() => onRemove("attention")}>Needs attention <X size={12} /></button>}{values.state && <button type="button" aria-label={`Remove ${operationStateLabel(values.state)} filter`} onClick={() => onRemove("state")}>{operationStateLabel(values.state)} <X size={12} /></button>}{values.provider && <button type="button" aria-label={`Remove provider ${values.provider} filter`} onClick={() => onRemove("provider")}>Provider: {values.provider} <X size={12} /></button>}{values.createdFrom && <button type="button" aria-label="Remove created from filter" onClick={() => onRemove("createdFrom")}>From: <code>{values.createdFrom}</code> <X size={12} /></button>}{values.createdTo && <button type="button" aria-label="Remove created to filter" onClick={() => onRemove("createdTo")}>To: <code>{values.createdTo}</code> <X size={12} /></button>}<button type="button" onClick={onClear}>Clear all</button></div>}
    </div>
  );
}

interface OperationIdNavigationProps {
  onNavigate: (operationId: string) => void;
}

export function OperationIdNavigation({ onNavigate }: OperationIdNavigationProps) {
  const [operationId, setOperationId] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (operationId.length > 0) onNavigate(operationId);
  }

  return (
    <form className="operation-id-navigation" aria-label="Open operation by exact ID" onSubmit={submit}>
      <label htmlFor="exact-operation-id">Exact operation ID</label>
      <input
        id="exact-operation-id"
        value={operationId}
        maxLength={200}
        onChange={(event) => setOperationId(event.currentTarget.value)}
      />
      <button type="submit" className="primitive-button">Open operation</button>
    </form>
  );
}
