import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { RtAlert, RtSnapshot } from "../types/api";

const MAX_FEED = 200;

/**
 * Subscribes to the backend SSE stream. EventSource reconnects on its own; while it is down the hook
 * reports `connected = false` and keeps the last snapshot rather than showing anything invented.
 */
export function useLiveStream() {
  const [snap, setSnap] = useState<RtSnapshot | null>(null);
  const [feed, setFeed] = useState<RtAlert[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let session: string | null = null;
    const es = new EventSource(api.rtStreamUrl());
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    const handle = (kind: "snapshot" | "update") => (e: Event) => {
      const data = JSON.parse((e as MessageEvent).data) as RtSnapshot;
      const sid = data.session?.id ?? null;
      setSnap(data);
      if (kind === "snapshot" || sid !== session) {
        // (re)connect or a new session: rebuild the feed from the server's recent alerts (newest first)
        setFeed(data.recent_alerts.slice(0, MAX_FEED));
      } else if (data.new_alerts?.length) {
        const fresh = data.new_alerts.slice().reverse(); // arrive oldest first
        setFeed((prev) => {
          const seen = new Set(prev.map((a) => a.id));
          return [...fresh.filter((a) => !seen.has(a.id)), ...prev].slice(0, MAX_FEED);
        });
      }
      session = sid;
    };
    es.addEventListener("snapshot", handle("snapshot"));
    es.addEventListener("tick", handle("update"));
    es.addEventListener("status", handle("update"));
    return () => es.close();
  }, []);

  return { snap, feed, connected };
}
