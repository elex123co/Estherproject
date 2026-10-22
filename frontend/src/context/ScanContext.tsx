import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../services/api";
import type { Scan } from "../types/api";

interface ScanContextValue {
  /** "" means all scans */
  scanId: string;
  setScanId: (id: string) => void;
  scans: Scan[];
  refreshScans: () => void;
}

const Ctx = createContext<ScanContextValue | null>(null);
const KEY = "nid.scope";

export function ScanProvider({ children }: { children: ReactNode }) {
  const [scanId, setScanIdState] = useState<string>(() => {
    try {
      return localStorage.getItem(KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [scans, setScans] = useState<Scan[]>([]);

  const refreshScans = useCallback(() => {
    api
      .scans(100)
      .then((r) => {
        setScans(r.items);
        // drop a stored scope that no longer exists (for example after a scan was deleted)
        setScanIdState((current) => (current && !r.items.some((s) => s.id === current) ? "" : current));
      })
      .catch(() => setScans([]));
  }, []);

  useEffect(() => {
    refreshScans();
  }, [refreshScans]);

  const setScanId = useCallback((id: string) => {
    setScanIdState(id);
    try {
      localStorage.setItem(KEY, id);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const value = useMemo(() => ({ scanId, setScanId, scans, refreshScans }), [scanId, setScanId, scans, refreshScans]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useScope(): ScanContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useScope must be used inside ScanProvider");
  return v;
}
