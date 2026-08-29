export interface OperationFilters {
  state?: string;
  attention?: boolean;
  provider?: string;
  createdFrom?: string;
  createdTo?: string;
  cursor?: string;
  limit?: number;
}

export function operationQuery(filters: OperationFilters = {}): string {
  const query = new URLSearchParams();
  if (filters.state !== undefined) query.set("state", filters.state);
  if (filters.attention) query.set("attention", "true");
  if (filters.provider !== undefined) query.set("provider", filters.provider);
  if (filters.createdFrom !== undefined) query.set("created_from", filters.createdFrom);
  if (filters.createdTo !== undefined) query.set("created_to", filters.createdTo);
  if (filters.cursor !== undefined) query.set("cursor", filters.cursor);
  if (filters.limit !== undefined) {
    if (!Number.isInteger(filters.limit) || filters.limit < 1 || filters.limit > 100) throw new RangeError("limit must be an integer from 1 to 100");
    query.set("limit", String(filters.limit));
  }
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}
