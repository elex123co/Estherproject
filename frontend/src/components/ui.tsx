import type { ReactNode } from "react";
import { ApiError } from "../services/api";
import type { ReviewStatus, RiskLevel, ScanStatus } from "../types/api";

export function Card(props: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; scroll?: boolean; className?: string }) {
  return (
    <section className={`card ${props.className ?? ""}`}>
      {(props.title || props.actions) && (
        <div className="card-header">
          <div>
            {props.title && <h2>{props.title}</h2>}
            {props.subtitle && <p>{props.subtitle}</p>}
          </div>
          {props.actions && <div className="row no-print">{props.actions}</div>}
        </div>
      )}
      <div className={`card-body ${props.flush ? "flush" : ""} ${props.scroll ? "scroll" : ""}`}>{props.children}</div>
    </section>
  );
}

export function StatCard(props: { label: string; value: ReactNode; hint?: ReactNode; tone?: "danger" | "warn" | "ok" | "review" }) {
  return (
    <div className={`card stat ${props.tone ? `tone-${props.tone}` : ""}`}>
      <div className="stat-label">{props.label}</div>
      <div className="stat-value">{props.value}</div>
      {props.hint && <div className="stat-hint">{props.hint}</div>}
    </div>
  );
}

export function RiskBadge({ level }: { level: RiskLevel | string }) {
  return (
    <span className={`badge risk-${level.replace(/ /g, "-")}`}>
      <span className="dot" />
      {level === "None" ? "No risk rule" : level}
    </span>
  );
}

export function ClassBadge({ suspicious }: { suspicious: boolean }) {
  return <span className={`badge ${suspicious ? "tag-suspicious" : "tag-normal"}`}>{suspicious ? "Suspicious" : "Normal"}</span>;
}

export function StatusBadge({ status }: { status: ScanStatus }) {
  return <span className={`badge status-${status}`}>{status}</span>;
}

export function ReviewBadge({ status }: { status: ReviewStatus }) {
  return <span className={`badge review-${status}`}>{status}</span>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" /> {label}...
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: Error | ApiError; onRetry?: () => void }) {
  const problems = error instanceof ApiError ? error.problems : [];
  return (
    <div className="banner error" role="alert">
      <div style={{ flex: 1 }}>
        <strong>Something went wrong.</strong> {error.message}
        {problems.length > 0 && (
          <ul>
            {problems.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        )}
      </div>
      {onRetry && (
        <button className="btn sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty(props: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{props.title}</h3>
      {props.children && <p>{props.children}</p>}
      {props.action}
    </div>
  );
}

export function Banner(props: { tone: "info" | "warn" | "error" | "ok"; children: ReactNode }) {
  return <div className={`banner ${props.tone}`}>{props.children}</div>;
}

export function Pager(props: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(props.total / props.pageSize));
  const from = props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1;
  const to = Math.min(props.total, props.page * props.pageSize);
  return (
    <div className="pager">
      <span className="muted small">
        {from.toLocaleString()}-{to.toLocaleString()} of {props.total.toLocaleString()}
      </span>
      <div className="row">
        <button className="btn sm" disabled={props.page <= 1} onClick={() => props.onPage(props.page - 1)}>
          Previous
        </button>
        <span className="small muted">
          Page {props.page} of {pages}
        </span>
        <button className="btn sm" disabled={props.page >= pages} onClick={() => props.onPage(props.page + 1)}>
          Next
        </button>
      </div>
    </div>
  );
}

export function Disclaimer() {
  return (
    <p className="muted small" style={{ margin: 0 }}>
      Decision-support prototype. Flagged records are potential intrusions that require investigation, not confirmed incidents. The system can
      miss attacks and can raise false alarms, and it does not replace professional security analysts.
    </p>
  );
}

const ICONS: Record<string, string> = {
  overview: "M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z",
  traffic: "M3 17l5-6 4 4 5-8 4 5M3 21h18",
  alerts: "M12 3l10 18H2zM12 10v5M12 18v.01",
  upload: "M12 16V4m0 0l-4 4m4-4l4 4M4 20h16",
  model: "M4 6h16M4 12h10M4 18h6M18 14l3 3-3 3",
  reports: "M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6",
  live: "M3 12h4l3-8 4 16 3-8h4",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  rules: "M5 5h14M5 12h14M5 19h14M8 3v4M16 10v4M10 17v4",
};

export function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}
