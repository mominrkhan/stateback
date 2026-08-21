import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { AuthSession } from "./auth/AuthSession";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthSession>
      <App />
    </AuthSession>
  </StrictMode>,
);
