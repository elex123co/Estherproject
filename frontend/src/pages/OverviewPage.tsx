import { Link } from "react-router-dom";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useScope } from "../context/ScanContext";
import { CategoryBars, RiskBars } from "../components/charts";
import { Card, Disclaimer, Empty, ErrorBox, Loading, StatCard, StatusBadge } from "../components/ui";
import { fmtDateTime, fmtInt, fmtPct } from "../utils/format";

export function OverviewPage() {
  const { scanId, scans } = useScope();
  const { data, error, loading, reload } = useAsync(() => api.overview(scanId || undefined), [scanId]);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Overview</h1>
          <p>Summary of stored analysis results {scanId ? "for the selected analysis" : "across all analyses"}.</p>
        </div>
      </div>

      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}

      {data && data.total_records === 0 && (
        <Card>
          <Empty
            title="No analysis results yet"
            action={<Link className="btn primary" to="/upload">Upload a dataset</Link>}
          >
            Upload a CSV of network flows and run an analysis. Every figure on this dashboard is computed from stored model output, so it stays empty until then.
          </Empty>
        </Card>
      )}

      {data && data.total_records > 0 && (
        <>
          <div className="grid c5">
            <StatCard label="Records analyzed" value={fmtInt(data.total_records)} hint="Network flows, not unique incidents" />
            <StatCard label="Classified normal" value={fmtInt(data.normal_records)} tone="ok" hint={fmtPct(data.normal_records / data.total_records)} />
            <StatCard label="Flagged suspicious" value={fmtInt(data.suspicious_records)} tone="danger" hint={fmtPct(data.suspicious_records / data.total_records)} />
            <StatCard label="Require review" value={fmtInt(data.records_requiring_review)} tone="review" hint="Uncertain or incomplete results" />
            <StatCard label="Analyses completed" value={fmtInt(data.scans_completed)} hint={data.last_analysis_at ? `Last: ${fmtDateTime(data.last_analysis_at)}` : undefined} />
          </div>

          <div className="grid c2">
            <Card title="Alerts by risk level" subtitle="Application risk rules applied to flagged records">
              <RiskBars counts={data.alerts_by_risk} />
            </Card>
            <Card title="Most frequently predicted attack categories" subtitle="Count of records per predicted category">
              {data.top_attack_categories.length === 0 ? (
                <Empty title="No suspicious records">The model flagged nothing in this scope.</Empty>
              ) : (
                <CategoryBars data={data.top_attack_categories} />
              )}
            </Card>
          </div>

          <div className="grid c-2-1">
            <Card title="Recent analyses" flush scroll actions={<Link to="/upload" className="btn sm">Upload dataset</Link>}>
              <table className="data">
                <thead>
                  <tr><th>Source</th><th>Status</th><th className="num">Records</th><th className="num">Flagged</th><th>Finished</th></tr>
                </thead>
                <tbody>
                  {scans.slice(0, 6).map((s) => (
                    <tr key={s.id}>
                      <td>{s.filename ?? "Single record"}</td>
                      <td><StatusBadge status={s.status} /></td>
                      <td className="num">{fmtInt(s.records_stored || s.rows_total)}</td>
                      <td className="num">{fmtInt(s.suspicious_records)}</td>
                      <td className="nowrap">{fmtDateTime(s.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="Alert review progress">
              <dl className="kv" style={{ gridTemplateColumns: "1fr auto" }}>
                <dt>New</dt><dd>{fmtInt(data.alerts_by_review_status.new)}</dd>
                <dt>Investigating</dt><dd>{fmtInt(data.alerts_by_review_status.investigating)}</dd>
                <dt>Reviewed</dt><dd>{fmtInt(data.alerts_by_review_status.reviewed)}</dd>
              </dl>
              <div style={{ marginTop: 12 }}><Link className="btn sm" to="/alerts">Open alert queue</Link></div>
            </Card>
          </div>

          <Card title="How to read these results">
            <div className="three-way">
              <div><h3>Prediction</h3><p className="muted small" style={{ margin: 0 }}>What the machine-learning model thinks the flow is: normal, or a specific attack category from its training data.</p></div>
              <div><h3>Model confidence</h3><p className="muted small" style={{ margin: 0 }}>How strongly the model favours its own prediction. It is an estimate, not a calibrated probability, and it does not measure severity.</p></div>
              <div><h3>Risk level</h3><p className="muted small" style={{ margin: 0 }}>A separate, rule-based triage priority. It depends on the attack category and supporting evidence, and is never derived from confidence alone.</p></div>
            </div>
            <p className="muted small" style={{ margin: "12px 0 8px" }}>{data.note}</p>
            <Disclaimer />
          </Card>
        </>
      )}
    </>
  );
}
