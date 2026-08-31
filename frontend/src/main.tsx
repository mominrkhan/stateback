import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";

import { App } from "./app/App";
import { AuthSession, consumeBootstrapToken, restoreDevBootstrapToken } from "./auth/AuthSession";

const bootstrapToken = window.location.hash.startsWith("#stateback-bootstrap=")
  ? consumeBootstrapToken()
  : restoreDevBootstrapToken();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthSession initialToken={bootstrapToken}>
      <App />
      <Toaster theme="dark" position="bottom-right" richColors closeButton duration={1800} />
    </AuthSession>
  </StrictMode>,
);
