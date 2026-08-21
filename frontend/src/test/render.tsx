import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";

import { AuthSession } from "../auth/AuthSession";

export function renderWithSession(ui: ReactElement, options?: RenderOptions) {
  return render(<AuthSession>{ui}</AuthSession>, options);
}
