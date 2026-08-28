import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { AuthSession, consumeBootstrapToken } from "./auth/AuthSession";

const bootstrapToken = consumeBootstrapToken();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthSession initialToken={bootstrapToken}>
      <App />
    </AuthSession>
  </StrictMode>,
);
