import { NavLink, Outlet } from "react-router-dom";
import { Banner, Icon } from "../components/ui";
import { SystemStatus } from "../components/SystemStatus";
import { useHealthState } from "../context/HealthContext";
import { useScope } from "../context/ScanContext";
import { fmtDateTime } from "../utils/format";

const NAV = [
  { to: "/", label: "Overview", icon: "overview" },
  { to: "/live", label: "Live detection", icon: "live" },
  { to: "/traffic", label: "Traffic analysis", icon: "traffic" },
  { to: "/alerts", label: "Alerts and review", icon: "alerts" },
  { to: "/upload", label: "Upload and analyze", icon: "upload" },
  { to: "/model", label: "Model performance", icon: "model" },
  { to: "/reports", label: "Reports", icon: "reports" },
  { to: "/risk-rules", label: "Risk rules", icon: "rules" },
] as const;

export function AppLayout() {
  const { scanId, setScanId, scans } = useScope();
  const { state } = useHealthState();
  const analyzable = scans.filter((s) => s.status === "completed");

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#131d2a" />
            <path d="M16 5l9 3.5v7c0 5.2-3.7 9.2-9 11.5-5.3-2.3-9-6.3-9-11.5v-7z" fill="none" stroke="#4cc2d9" strokeWidth="2" strokeLinejoin="round" />
            <path d="M11.5 16.5h3l1.5-4 2 7 1.5-3h1" fill="none" stroke="#4cc2d9" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <div className="brand-title">Viona</div>
            <div className="brand-sub">Network threat detection</div>
          </div>
        </div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={n.icon} />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <SystemStatus />
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="scope">
            <label htmlFor="scope" className="muted small">Showing</label>
            <select id="scope" value={scanId} onChange={(e) => setScanId(e.target.value)} aria-label="Analysis scope">
              <option value="">All analyses</option>
              {analyzable.map((s) => (
                <option key={s.id} value={s.id}>
                  {(s.filename ?? "Single record")} - {fmtDateTime(s.finished_at ?? s.created_at)}
                </option>
              ))}
            </select>
          </div>
          <span className="muted small">Predictions are model estimates. Flagged records are potential intrusions, not confirmed incidents.</span>
        </header>
        <main className="page">
          {state.phase === "unreachable" && (
            <Banner tone="error">
              <div><strong>The backend is not reachable.</strong> {state.error} Pages below cannot show live results until it is running.</div>
            </Banner>
          )}
          {state.phase === "answered" && !state.health.model_loaded && (
            <Banner tone="error">
              <div><strong>No model is loaded.</strong> {state.health.model_error ?? ""} Train a model with backend/scripts/train.py, then restart the API.</div>
            </Banner>
          )}
          {state.phase === "answered" && state.health.model_is_synthetic && (
            <Banner tone="warn">
              <div><strong>Demo model.</strong> The loaded model was trained on synthetic smoke-test data, not real network traffic. Results demonstrate that the software works. They say nothing about real-world detection quality. Train on CICIDS2017 for meaningful results.</div>
            </Banner>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
