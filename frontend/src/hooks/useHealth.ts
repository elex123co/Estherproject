import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { Health } from "../types/api";

export type HealthState =
  | { phase: "checking" }
  | { phase: "unreachable"; error: string }
  | { phase: "answered"; health: Health };

/** Polls /api/health. Success is shown only when the endpoint actually answered. */
export function useHealth(intervalMs = 15000): { state: HealthState; recheck: () => void } {
  const [state, setState] = useState<HealthState>({ phase: "checking" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const run = () =>
      api
        .health()
        .then((health) => !cancelled && setState({ phase: "answered", health }))
        .catch((e: Error) => !cancelled && setState({ phase: "unreachable", error: e.message }));
    run();
    const timer = window.setInterval(run, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs, tick]);

  return { state, recheck: () => setTick((t) => t + 1) };
}
