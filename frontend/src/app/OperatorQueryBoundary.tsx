import { QueryClient, QueryClientContext, QueryClientProvider } from "@tanstack/react-query";
import { useContext, useState, type ReactNode } from "react";

export function OperatorQueryBoundary({ children }: { children: ReactNode }) {
  const inherited = useContext(QueryClientContext);
  const [local] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 15_000, refetchOnWindowFocus: false } } }));
  return inherited ? children : <QueryClientProvider client={local}>{children}</QueryClientProvider>;
}
