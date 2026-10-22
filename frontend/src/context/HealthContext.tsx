import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";
import { useHealth, type HealthState } from "../hooks/useHealth";

interface HealthCtx {
  state: HealthState;
  recheck: () => void;
  /** True only when the last health check answered and reported ready. */
  ready: boolean;
  /** True until the backend has answered once. A sleeping free host can take about a minute. */
  waking: boolean;
}

const Ctx = createContext<HealthCtx | null>(null);

export function HealthProvider({ children }: { children: ReactNode }) {
  const { state, recheck, everAnswered } = useHealth();
  // The page may have loaded while a sleeping host was still waking, so its first data requests failed.
  // Once the server answers, reload once so every page fetches fresh data.
  const sawDown = useRef(false);
  useEffect(() => {
    if (state.phase === "unreachable") sawDown.current = true;
    if (state.phase === "answered" && sawDown.current) window.location.reload();
  }, [state]);
  const ready = state.phase === "answered" && state.health.ready;
  return <Ctx.Provider value={{ state, recheck, ready, waking: !everAnswered }}>{children}</Ctx.Provider>;
}

export function useHealthState(): HealthCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useHealthState must be used inside HealthProvider");
  return v;
}
