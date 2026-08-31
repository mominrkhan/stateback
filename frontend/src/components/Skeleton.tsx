export function Skeleton({ variant = "page", label = "Loading content" }: { variant?: "page" | "table" | "detail" | "cards"; label?: string }) {
  const rows = variant === "table" ? 6 : variant === "detail" ? 5 : 4;
  return <div className={`skeleton-layout skeleton-layout--${variant}`} role="status" aria-label={label}><span className="visually-hidden">{label}</span><div className="skeleton skeleton--title" />{Array.from({ length: rows }, (_, index) => <div className="skeleton" key={index} />)}</div>;
}
