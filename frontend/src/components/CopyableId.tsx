import { useId, useState } from "react";

export interface CopyableIdProps {
  value: string;
  label?: string;
}

export function CopyableId({ value, label = "identifier" }: CopyableIdProps) {
  const [announcement, setAnnouncement] = useState("");
  const statusId = useId();

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setAnnouncement(`${label} copied`);
    } catch {
      setAnnouncement(`Unable to copy ${label}`);
    }
  }

  return (
    <span className="copyable-id">
      <code aria-label={`${label}: ${value}`} title={value}>{value}</code>
      <button
        type="button"
        className="primitive-button"
        aria-describedby={statusId}
        aria-label={`Copy ${label} ${value}`}
        onClick={() => void copy()}
      >
        Copy
      </button>
      <span id={statusId} role="status" className="visually-hidden">{announcement}</span>
    </span>
  );
}
