import type { RiskLevel } from "../types/api";

export const RISK_ORDER: RiskLevel[] = ["Critical", "High", "Medium", "Low", "Needs review", "None"];

export const RISK_COLOR: Record<string, string> = {
  Critical: "var(--risk-critical)",
  High: "var(--risk-high)",
  Medium: "var(--risk-medium)",
  Low: "var(--risk-low)",
  "Needs review": "var(--risk-review)",
  None: "var(--risk-none)",
};

export const RISK_HEX: Record<string, string> = {
  Critical: "#ef4f5f",
  High: "#f0873a",
  Medium: "#e5b93c",
  Low: "#55a6e6",
  "Needs review": "#a78bfa",
  None: "#3fae85",
};

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "-" : n.toLocaleString();
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  return x === null || x === undefined ? "n/a" : `${(x * 100).toFixed(digits)}%`;
}

export function fmtNum(x: number | null | undefined, digits = 4): string {
  return x === null || x === undefined ? "n/a" : x.toFixed(digits);
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Flow timestamps carry no timezone; show them as written instead of converting. */
export function fmtEventTime(iso: string, source: "flow" | "processed"): string {
  if (source === "flow") return iso.replace("T", " ").slice(0, 16);
  return fmtDateTime(iso.length === 19 ? iso + "Z" : iso);
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n && n !== 0) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function fmtFeatureValue(v: number | null | undefined): string {
  if (v === null || v === undefined) return "missing";
  if (Number.isInteger(v)) return v.toLocaleString();
  return Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : v.toPrecision(5).replace(/\.?0+$/, "");
}

/** `datetime-local` input value -> backend ISO string (no timezone, matches stored flow times). */
export function localInputToIso(v: string): string | undefined {
  return v ? (v.length === 16 ? `${v}:00` : v) : undefined;
}
