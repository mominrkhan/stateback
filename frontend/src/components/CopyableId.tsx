import { Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

export interface CopyableIdProps { value: string; label?: string }

export function CopyableId({ value, label = "identifier" }: CopyableIdProps) {
  const [announcement, setAnnouncement] = useState("");
  async function copy() {
    try { await navigator.clipboard.writeText(value); setAnnouncement(`${label} copied`); toast.success(`${label} copied`); }
    catch { setAnnouncement(`Unable to copy ${label}`); toast.error(`Unable to copy ${label}`); }
  }
  return <span className="copyable-id"><code aria-label={`${label}: ${value}`} title={value}>{value}</code><button type="button" className="icon-button copyable-id__button" aria-label={`Copy ${label} ${value}`} onClick={() => void copy()}><Copy size={14} aria-hidden="true" /></button><span role="status" className="visually-hidden">{announcement}</span></span>;
}
