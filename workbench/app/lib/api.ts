import type { BusEvent, RequestView, SystemOverview } from "./types";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

export const api = {
  system: () => get<SystemOverview>("/api/system"),
  requests: () => get<RequestView[]>("/api/requests"),
  request: (rid: string) => get<RequestView>(`/api/requests/${rid}`),
  events: (after = 0) => get<BusEvent[]>(`/api/events?after=${after}`),
  topics: () => get<string[]>("/api/bus/topics"),
  storage: () => get<Record<string, string[]>>("/api/storage"),
  storageRead: (key: string) =>
    get<{ key: string; bytes: number; preview: string }>(
      `/api/storage/read?key=${encodeURIComponent(key)}`),
  replay: (topic: string) => get<unknown[]>(`/api/replay/${topic}`),
  kernelLog: () => get<Record<string, unknown>[]>("/api/kernel/log"),
  submit: async (intent: string, goals: string[]): Promise<RequestView> => {
    const response = await fetch("/api/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent, goals }),
    });
    if (!response.ok) throw new Error(`submit: ${response.status}`);
    return response.json();
  },
};
