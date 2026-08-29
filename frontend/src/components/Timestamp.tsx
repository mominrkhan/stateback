export function formatUtcTimestamp(value: string): string | null {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? null : parsed.toISOString();
}

function relativeTimestamp(value: string): string {
  const seconds = Math.round((new Date(value).valueOf() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

export function Timestamp({ value, relative = false }: { value: string; relative?: boolean }) {
  const formatted = formatUtcTimestamp(value);
  if (formatted === null) return <span role="status">Invalid timestamp</span>;
  return <time dateTime={value} title={`${formatted} UTC`}>{relative ? relativeTimestamp(value) : `${formatted} UTC`}</time>;
}
