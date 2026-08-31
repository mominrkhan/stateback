import { Copy } from "lucide-react";
import { toast } from "sonner";

export function CopyCommand({ command }: { command: string }) {
  async function copy() {
    try { await navigator.clipboard.writeText(command); toast.success("Command copied"); }
    catch { toast.error("Unable to copy command"); }
  }
  return <span className="copy-command"><code>{command}</code><button type="button" className="primitive-button" onClick={() => void copy()}><Copy size={15} aria-hidden="true" /> Copy command</button></span>;
}
