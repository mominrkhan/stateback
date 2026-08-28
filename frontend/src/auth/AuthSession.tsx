import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type SessionClearReason = "logout" | "unauthorized";

export interface AuthSessionValue {
  authenticated: boolean;
  sessionGeneration: number;
  getAccessToken: () => string;
  beginSession: (token: string) => boolean;
  clearSession: (reason: SessionClearReason) => void;
  createAbortController: () => AbortController;
  releaseAbortController: (controller: AbortController) => void;
  isCurrentGeneration: (generation: number) => boolean;
  accessMessage: string | null;
}

const AuthSessionContext = createContext<AuthSessionValue | null>(null);

const BOOTSTRAP_PREFIX = "#stateback-bootstrap=";
const DEV_TOKEN = /^[A-Za-z0-9_-]{32,128}$/u;

export function consumeBootstrapToken(): string | null {
  if (!window.location.hash.startsWith(BOOTSTRAP_PREFIX)) return null;
  const token = window.location.hash.slice(BOOTSTRAP_PREFIX.length);
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${window.location.search}`,
  );
  return DEV_TOKEN.test(token) ? token : null;
}

export function AuthSession({
  children,
  initialToken = null,
}: {
  children: ReactNode;
  initialToken?: string | null;
}) {
  const tokenRef = useRef(initialToken ?? "");
  const generationRef = useRef(0);
  const abortControllers = useRef(new Set<AbortController>());
  const [authenticated, setAuthenticated] = useState(Boolean(initialToken));
  const [sessionGeneration, setSessionGeneration] = useState(0);
  const [accessMessage, setAccessMessage] = useState<string | null>(null);

  const abortRequests = useCallback(() => {
    for (const controller of abortControllers.current) controller.abort();
    abortControllers.current.clear();
  }, []);

  const beginSession = useCallback((token: string) => {
    if (token.length === 0) return false;
    tokenRef.current = token;
    setAccessMessage(null);
    setAuthenticated(true);
    return true;
  }, []);

  const clearSession = useCallback((reason: SessionClearReason) => {
    tokenRef.current = "";
    abortRequests();
    generationRef.current += 1;
    setSessionGeneration(generationRef.current);
    setAuthenticated(false);
    setAccessMessage(reason === "unauthorized" ? "Session expired or token rejected" : null);
    window.history.replaceState(null, "", "/");
  }, [abortRequests]);

  const createAbortController = useCallback(() => {
    const controller = new AbortController();
    abortControllers.current.add(controller);
    controller.signal.addEventListener(
      "abort",
      () => abortControllers.current.delete(controller),
      { once: true },
    );
    return controller;
  }, []);

  const releaseAbortController = useCallback((controller: AbortController) => {
    abortControllers.current.delete(controller);
  }, []);

  const value = useMemo<AuthSessionValue>(() => ({
    authenticated,
    sessionGeneration,
    getAccessToken: () => tokenRef.current,
    beginSession,
    clearSession,
    createAbortController,
    releaseAbortController,
    isCurrentGeneration: (generation) => generation === generationRef.current,
    accessMessage,
  }), [
    accessMessage,
    authenticated,
    beginSession,
    clearSession,
    createAbortController,
    releaseAbortController,
    sessionGeneration,
  ]);

  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

export function useAuthSession(): AuthSessionValue {
  const session = useContext(AuthSessionContext);
  if (!session) throw new Error("useAuthSession must be used within AuthSession");
  return session;
}
