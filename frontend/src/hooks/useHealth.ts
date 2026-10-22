import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { Health } from "../types/api";

export type HealthState =
  | { phase: "checking" }
  | { phase: "unreachable"; error: string }
  | { phase: "answered"; health: Health };

/** Polls /api/health. Success is shown only when the endpoint actually answered. */
export function useHealth(intervalMs = 15000): { state: HealthState; recheck: () => void; everAnswered: boolean } {
  const [state, setState] = useState<HealthState>({ phase: "checking" });
  const [everAnswered, setEver] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let answered = false;
    // Poll every 4 s until the server first answers (a sleeping free host takes up to a minute), then back off.
    const loop = () => {
      run().finally(() => {
        if (!cancelled) timer = window.setTimeout(loop, answered ? intervalMs : 4000);
      });
    };
    const run = () =>
      api
        .health()
        .then((health) => {
          answered = true;
          setEver(true);
          if (!cancelled) setState({ phase: "answered", health });
        })
        .catch((e: Error) => {
          if (!cancelled) setState({ phase: "unreachable", error: e.message });
        });
    loop();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [intervalMs, tick]);

  return { state, recheck: () => setTick((t) => t + 1), everAnswered };
}
