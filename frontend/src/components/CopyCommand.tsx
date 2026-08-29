import { useState } from "react";

export function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <span className="copy-command">
      <code>{command}</code>
      <button type="button" className="primitive-button" onClick={() => void copy()}>
        {copied ? "Copied" : "Copy command"}
      </button>
    </span>
  );
}
