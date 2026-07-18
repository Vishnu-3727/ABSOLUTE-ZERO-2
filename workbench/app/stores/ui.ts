"use client";
// UI state only (Zustand). Server state lives in TanStack Query; live
// events arrive over the WebSocket and are buffered here for rendering.
import { create } from "zustand";
import type { BusEvent } from "@/lib/types";

const MAX_FEED = 2000;

interface UiState {
  selectedRequest: string | null;
  liveFeed: BusEvent[];
  wsConnected: boolean;
  selectRequest: (rid: string | null) => void;
  pushEvents: (events: BusEvent[]) => void;
  setConnected: (connected: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  selectedRequest: null,
  liveFeed: [],
  wsConnected: false,
  selectRequest: (rid) => set({ selectedRequest: rid }),
  pushEvents: (events) =>
    set((state) => {
      const seen = new Set(state.liveFeed.map((e) => e.seq));
      const fresh = events.filter((e) => !seen.has(e.seq));
      if (!fresh.length) return state;
      return {
        liveFeed: [...state.liveFeed, ...fresh]
          .sort((a, b) => a.seq - b.seq)
          .slice(-MAX_FEED),
      };
    }),
  setConnected: (connected) => set({ wsConnected: connected }),
}));
