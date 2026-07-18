"use client";
// The one WebSocket. Events flow bus -> gateway -> here -> Zustand buffer;
// query invalidation keeps REST caches honest without polling.
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUi } from "@/stores/ui";
import type { BusEvent } from "./types";

export function useEventSocket() {
  const pushEvents = useUi((s) => s.pushEvents);
  const setConnected = useUi((s) => s.setConnected);
  const queryClient = useQueryClient();

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;

    function connect() {
      socket = new WebSocket("ws://localhost:8777/ws/events");
      socket.onopen = async () => {
        setConnected(true);
        // hydrate history so the feed shows events from before this page load
        const history = await fetch("/api/events").then((r) => r.json());
        pushEvents(history);
      };
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data) as BusEvent;
        pushEvents([event]);
        if (event.topic.startsWith("request.") || event.topic.startsWith("task.")) {
          queryClient.invalidateQueries({ queryKey: ["system"] });
          queryClient.invalidateQueries({ queryKey: ["requests"] });
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) setTimeout(connect, 2000);
      };
    }
    connect();
    return () => {
      closed = true;
      socket?.close();
    };
  }, [pushEvents, setConnected, queryClient]);
}
