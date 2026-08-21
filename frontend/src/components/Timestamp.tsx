export function formatUtcTimestamp(value: string): string | null {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? null : parsed.toISOString();
}

export function Timestamp({ value }: { value: string }) {
  const formatted = formatUtcTimestamp(value);
  if (formatted === null) return <span role="status">Invalid timestamp</span>;
  return <time dateTime={value}>{formatted} UTC</time>;
}
