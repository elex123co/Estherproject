import { Fragment } from "react";
import { useEffect, useState } from "react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useScope } from "../context/ScanContext";
import { CategoryBars, RiskBars } from "../components/charts";
import { Banner, Card, Empty, ErrorBox, Loading, ReviewBadge, RiskBadge, StatCard } from "../components/ui";
import { fmtDateTime, fmtEventTime, fmtInt, fmtPct, shortId } from "../utils/format";

export function ReportsPage() {
  const { scans, scanId } = useScope();
  const completed = scans.filter((s) => s.status === "completed");
  const [selected, setSelected] = useState("");
  const [includeContext, setIncludeContext] = useState(false);

  useEffect(() => {
    if (selected && completed.some((s) => s.id === selected)) return;
    const preferred = completed.find((s) => s.id === scanId) ?? completed[0];
    setSelected(preferred?.id ?? "");
  }, [completed, scanId, selected]);

  const report = useAsync(() => (selected ? api.report(selected) : Promise.resolve(null)), [selected]);
  const r = report.data;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p>Generate a report from a completed analysis. Raw flow features are never included, and IP addresses only if you ask for them.</p>
        </div>
      </div>

      {completed.length === 0 ? (
        <Card><Empty title="No completed analyses">Run an analysis first. Reports are built from stored results.</Empty></Card>
      ) : (
        <Card>
          <div className="filters">
            <label className="field">Analysis
              <select value={selected} onChange={(e) => setSelected(e.target.value)} style={{ maxWidth: 420 }}>
                {completed.map((s) => <option key={s.id} value={s.id}>{s.filename ?? "Single record"} - {fmtDateTime(s.finished_at)}</option>)}
              </select>
            </label>
            <label className="row small"><input type="checkbox" checked={includeContext} onChange={(e) => setIncludeContext(e.target.checked)} /> Include IP addresses and destination port in CSV</label>
            {selected && (
              <>
                <a className="btn" href={api.exportUrl(selected, "alerts", includeContext)}>Download flagged records (CSV)</a>
                <a className="btn" href={api.exportUrl(selected, "all", includeContext)}>Download all records (CSV)</a>
                <button className="btn primary" onClick={() => window.print()}>Print or save as PDF</button>
              </>
            )}
          </div>
        </Card>
      )}

      {report.loading && !r && selected && <Loading />}
      {report.error && <ErrorBox error={report.error} onRetry={report.reload} />}

      {r && (
        <>
          <div className="card" style={{ padding: 20 }}>
            <h1>Network intrusion analysis report</h1>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Source: {r.scan.filename ?? "Single record"} / Analysis date: {fmtDateTime(r.scan.finished_at)} / Report generated: {fmtDateTime(r.generated_at)}
            </p>
            <p className="muted small" style={{ margin: "4px 0 0" }}>
              Model {r.model.type ?? "-"} version <span className="mono">{r.model.version}</span>, trained {fmtDateTime(r.model.trained_at)} on {r.model.training_dataset ?? "unknown"}. Risk rules v{r.risk_rules_version}.
            </p>
          </div>

          {r.model.is_synthetic && <Banner tone="warn"><div><strong>Demo model.</strong> This report was produced by a model trained on synthetic data. It does not reflect real-world detection quality.</div></Banner>}

          <div className="grid c4">
            <StatCard label="Records analyzed" value={fmtInt(r.scan.records_stored)} hint="Flows, not unique incidents" />
            <StatCard label="Normal" value={fmtInt(r.classification.normal)} tone="ok" />
            <StatCard label="Suspicious" value={fmtInt(r.classification.suspicious)} tone="danger" />
            <StatCard label="Require review" value={fmtInt(r.scan.records_requiring_review)} tone="review" />
          </div>

          <Card title="Dataset summary">
            <dl className="kv">
              <dt>Records in file</dt><dd>{fmtInt(r.dataset_summary.records)}</dd>
              <dt>Features</dt><dd>{r.dataset_summary.features_detected ?? "-"} of {r.dataset_summary.features_expected ?? "-"} expected</dd>
              <dt>Missing / invalid values</dt><dd>{fmtInt(r.dataset_summary.missing_values)} / {fmtInt(r.dataset_summary.invalid_values)}</dd>
              <dt>Duplicate rows</dt><dd>{fmtInt(r.dataset_summary.duplicate_rows)}</dd>
              {r.dataset_summary.warnings.length > 0 && <><dt>Warnings</dt><dd>{r.dataset_summary.warnings.map((w, i) => <div key={i}>{w}</div>)}</dd></>}
            </dl>
          </Card>

          <div className="grid c2">
            <Card title="Risk distribution"><RiskBars counts={r.risk_levels} includeNone /></Card>
            <Card title="Predicted categories"><CategoryBars data={r.categories} /></Card>
          </div>

          {r.summary?.label_comparison && (
            <Card title="Comparison with labels supplied in the file" subtitle={r.summary.label_comparison.basis}>
              <dl className="kv">
                <dt>Attack recall</dt><dd>{fmtPct(r.summary.label_comparison.binary_detection.recall, 2)}</dd>
                <dt>Attack precision</dt><dd>{fmtPct(r.summary.label_comparison.binary_detection.precision, 2)}</dd>
                <dt>False-positive rate</dt><dd>{fmtPct(r.summary.label_comparison.binary_detection.false_positive_rate, 3)}</dd>
                <dt>Macro F1 / accuracy</dt><dd>{r.summary.label_comparison.macro_avg.f1.toFixed(4)} / {fmtPct(r.summary.label_comparison.accuracy, 2)}</dd>
              </dl>
              <p className="faint small" style={{ margin: "8px 0 0" }}>{r.summary.label_comparison.caveat}</p>
            </Card>
          )}

          {r.summary?.realtime && (
            <Card title="Real-time session" subtitle={`Mode: ${r.summary.realtime.mode}. Ended: ${r.summary.realtime.stop_reason ?? "n/a"}.`}>
              <dl className="kv">
                <dt>Average throughput</dt><dd>{r.summary.realtime.avg_throughput_flows_per_s} flows/s</dd>
                <dt>Latency p50 / p95 / max</dt>
                <dd>{r.summary.realtime.latency_ms ? `${r.summary.realtime.latency_ms.p50.toFixed(1)} / ${r.summary.realtime.latency_ms.p95.toFixed(1)} / ${r.summary.realtime.latency_ms.max.toFixed(1)} ms` : "n/a"}</dd>
                {r.summary.realtime.phases.map((p) => (
                  <Fragment key={p.idx}>
                    <dt>Injected: {p.label}</dt>
                    <dd>{fmtInt(p.flows ?? 0)} flows, {p.recall === null ? "n/a" : fmtPct(p.recall, 1)} flagged, first detection {p.first_detection_s == null ? "not detected" : `${p.first_detection_s.toFixed(2)} s after start`}</dd>
                  </Fragment>
                ))}
              </dl>
              <p className="faint small" style={{ margin: "8px 0 0" }}>{r.summary.realtime.latency_note}</p>
            </Card>
          )}

          <Card title="Highest-priority flagged records" subtitle="Up to 50, ordered by risk then model confidence" flush scroll>
            {r.top_alerts.length === 0 ? <Empty title="Nothing was flagged" /> : (
              <table className="data">
                <thead><tr><th>Record</th><th>Event time</th><th>Predicted class</th><th className="num">Confidence</th><th>Risk</th><th>Rule</th><th>Review</th></tr></thead>
                <tbody>
                  {r.top_alerts.map((a) => (
                    <tr key={a.id}>
                      <td className="mono">{shortId(a.id)}</td>
                      <td className="nowrap">{fmtEventTime(a.event_time, a.event_time.length === 19 && !a.event_time.includes("+") ? "flow" : "processed")}</td>
                      <td>{a.predicted_class}</td>
                      <td className="num">{a.confidence === null ? "n/a" : fmtPct(a.confidence)}</td>
                      <td><RiskBadge level={a.risk_level} /></td>
                      <td className="mono small">{a.risk_rule_id}</td>
                      <td><ReviewBadge status={a.review_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card>
            <p className="small" style={{ margin: "0 0 6px" }}>{r.counting_note}</p>
            <p className="muted small" style={{ margin: 0 }}>{r.disclaimer}</p>
          </Card>
        </>
      )}
    </>
  );
}
