import { createContext, useContext, type ReactNode } from "react";
import { useHealth, type HealthState } from "../hooks/useHealth";

interface HealthCtx {
  state: HealthState;
  recheck: () => void;
  /** True only when the last health check answered and reported ready. */
  ready: boolean;
}

const Ctx = createContext<HealthCtx | null>(null);

export function HealthProvider({ children }: { children: ReactNode }) {
  const { state, recheck } = useHealth();
  const ready = state.phase === "answered" && state.health.ready;
  return <Ctx.Provider value={{ state, recheck, ready }}>{children}</Ctx.Provider>;
}

export function useHealthState(): HealthCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useHealthState must be used inside HealthProvider");
  return v;
}
