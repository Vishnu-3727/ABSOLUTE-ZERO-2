"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { useEventSocket } from "@/lib/ws";

function SocketBridge({ children }: { children: React.ReactNode }) {
  useEventSocket();
  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 5000 } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <SocketBridge>{children}</SocketBridge>
    </QueryClientProvider>
  );
}
