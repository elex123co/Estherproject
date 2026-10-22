import { useHealthState } from "../context/HealthContext";

function Line({ ok, label, detail }: { ok: boolean | null; label: string; detail?: string }) {
  return (
    <div className="line">
      <span className={`dot-status ${ok === null ? "wait" : ok ? "ok" : "bad"}`} aria-hidden="true" />
      <span>{label}</span>
      {detail && <span className="faint" style={{ marginLeft: "auto" }}>{detail}</span>}
    </div>
  );
}

/** Shows only what the last /api/health call actually reported. */
export function SystemStatus() {
  const { state, recheck, waking } = useHealthState();

  if (state.phase === "checking") {
    return (
      <div className="status-card" aria-live="polite">
        <Line ok={null} label="Checking system..." />
      </div>
    );
  }
  if (state.phase === "unreachable" && waking) {
    return (
      <div className="status-card" aria-live="polite">
        <Line ok={null} label="Waking the server..." />
      </div>
    );
  }
  if (state.phase === "unreachable") {
    return (
      <div className="status-card" role="alert">
        <Line ok={false} label="Backend unreachable" />
        <Line ok={null} label="Model not checked" />
        <div className="err">{state.error}</div>
        <button className="btn sm" style={{ marginTop: 8 }} onClick={recheck}>Check again</button>
      </div>
    );
  }
  const h = state.health;
  return (
    <div className="status-card" aria-live="polite">
      <Line ok={h.backend_reachable} label="Backend reachable" />
      <Line ok={h.model_loaded} label="Model loaded" detail={h.model_loaded ? undefined : "failed"} />
      <Line ok={h.database_ok} label="Database" />
      <Line ok={h.ready} label={h.ready ? "Ready to analyze" : "Not ready"} />
      {h.model_error && <div className="err">{h.model_error}</div>}
      {h.database_error && <div className="err">{h.database_error}</div>}
      {h.model_version && <div className="faint mono" style={{ marginTop: 6, wordBreak: "break-all" }}>{h.model_version}</div>}
    </div>
  );
}
