import { useEffect, useState } from "react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import type { RecordDetail, ReviewStatus } from "../types/api";
import { fmtDateTime, fmtEventTime, fmtFeatureValue, fmtPct, shortId } from "../utils/format";
import { ClassBadge, ErrorBox, Loading, ReviewBadge, RiskBadge } from "./ui";

const STATUSES: { value: ReviewStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "investigating", label: "Investigating" },
  { value: "reviewed", label: "Reviewed" },
];

/** Detail view for one analyzed record / alert, with review controls. */
export function RecordDrawer({ recordId, onClose, onChanged }: { recordId: string; onClose: () => void; onChanged: () => void }) {
  const { data, error, loading } = useAsync(() => api.alert(recordId), [recordId]);
  const [record, setRecord] = useState<RecordDetail | null>(null);
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<ReviewStatus>("new");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data) {
      setRecord(data);
      setNote(data.review_note ?? "");
      setStatus(data.review_status);
      setSaved(false);
    }
  }, [data]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const dirty = record !== null && (status !== record.review_status || note !== (record.review_note ?? ""));

  async function save() {
    if (!record) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.review(record.id, { review_status: status, review_note: note });
      setRecord({ ...record, ...updated });
      setSaved(true);
      onChanged();
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="overlay" onClick={onClose} role="presentation">
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Record details">
        <div className="drawer-head">
          <div>
            <h2>{record?.is_suspicious ? "Potential intrusion" : record?.requires_review ? "Uncertain result" : "Analyzed record"}</h2>
            <div className="muted small mono">ID {record ? shortId(record.id) : "..."} {record && `/ row ${record.row_index}`}</div>
          </div>
          <button className="btn sm" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          {loading && !record && <Loading />}
          {error && <ErrorBox error={error} />}
          {record && (
            <>
              <p className="muted small" style={{ margin: 0 }}>
                {record.is_suspicious
                  ? "The model flagged this record as suspicious activity. It requires investigation and is not a confirmed incident."
                  : record.requires_review
                    ? "The model predicted normal activity, but the result is uncertain and needs verification."
                    : "The model predicted normal activity for this record."}
              </p>

              <div className="stack">
                <div className="panel">
                  <h3>Model prediction</h3>
                  <dl className="kv">
                    <dt>Predicted class</dt>
                    <dd><strong>{record.predicted_class}</strong></dd>
                    <dt>Policy</dt>
                    <dd><ClassBadge suspicious={record.is_suspicious} /></dd>
                    <dt>Model confidence</dt>
                    <dd>
                      {record.confidence === null ? "Not available" : fmtPct(record.confidence)}
                      {record.confidence !== null && (
                        <div className="meter"><div style={{ width: `${record.confidence * 100}%` }} /></div>
                      )}
                    </dd>
                  </dl>
                  <p className="faint small" style={{ margin: "8px 0 0" }}>{record.confidence_note}</p>
                </div>
                <div className="panel">
                  <h3>Risk assessment (rules)</h3>
                  <dl className="kv">
                    <dt>Risk level</dt>
                    <dd><RiskBadge level={record.risk_level} />{record.requires_review && <span className="badge risk-Needs-review" style={{ marginLeft: 6 }}>Requires review</span>}</dd>
                    <dt>Rule</dt>
                    <dd className="mono">{record.risk_rule_id ?? "-"}</dd>
                    <dt>Why</dt>
                    <dd>{record.risk_reason}</dd>
                    {Object.keys(record.risk_evidence ?? {}).length > 0 && (
                      <>
                        <dt>Evidence used</dt>
                        <dd>
                          {Object.entries(record.risk_evidence).map(([k, v]) => (
                            <span className="chip" key={k}>{k}: {fmtFeatureValue(v)}</span>
                          ))}
                        </dd>
                      </>
                    )}
                  </dl>
                  <p className="faint small" style={{ margin: "8px 0 0" }}>The risk level is a separate output from the prediction and the confidence.</p>
                </div>
              </div>

              <div className="panel">
                <h3>Record context</h3>
                <dl className="kv">
                  <dt>Event time</dt>
                  <dd>{fmtEventTime(record.event_time, record.event_time_source)} <span className="faint small">({record.event_time_source === "flow" ? "from the data" : "processing time"})</span></dd>
                  <dt>Processed</dt>
                  <dd>{fmtDateTime(record.processed_at)}</dd>
                  <dt>Source / destination</dt>
                  <dd>{record.src_ip ?? "-"} to {record.dst_ip ?? "-"}{record.dst_port !== null && `:${record.dst_port}`}</dd>
                  <dt>Supplied label</dt>
                  <dd>{record.ground_truth_label ?? "None supplied"} <span className="faint small">(ground truth from the file, not a prediction)</span></dd>
                </dl>
                {record.warnings.length > 0 && (
                  <div className="banner warn" style={{ marginTop: 10 }}>
                    <div>{record.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>
                  </div>
                )}
              </div>

              <div className="panel">
                <h3>Review</h3>
                <div className="row" style={{ marginBottom: 10 }}>
                  <div className="seg" role="group" aria-label="Review status">
                    {STATUSES.map((s) => (
                      <button key={s.value} className={status === s.value ? "on" : ""} onClick={() => setStatus(s.value)}>{s.label}</button>
                    ))}
                  </div>
                  <ReviewBadge status={record.review_status} />
                  {record.reviewed_at && <span className="faint small">updated {fmtDateTime(record.reviewed_at)}</span>}
                </div>
                <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} placeholder="Add a review note (what was checked, outcome, follow-up)" aria-label="Review note" />
                <div className="row spread" style={{ marginTop: 8 }}>
                  <span className="small">
                    {saveError && <span style={{ color: "#ff9aa4" }}>{saveError}</span>}
                    {saved && !dirty && <span className="muted">Saved.</span>}
                  </span>
                  <button className="btn primary" disabled={!dirty || saving} onClick={save}>{saving ? "Saving..." : "Save review"}</button>
                </div>
              </div>

              <div className="panel">
                <h3>Feature evidence</h3>
                {record.influential_features ? (
                  <>
                    <table className="data" style={{ marginBottom: 6 }}>
                      <thead><tr><th>Feature</th><th className="num">This record</th><th className="num">Model-wide importance</th></tr></thead>
                      <tbody>
                        {record.influential_features.map((f) => (
                          <tr key={f.feature}>
                            <td>{f.feature}</td>
                            <td className="num">{fmtFeatureValue(f.value)}</td>
                            <td className="num">{f.importance.toFixed(3)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="faint small">{record.influential_features_note}</p>
                  </>
                ) : (
                  <p className="faint small">{record.features_note ?? "This model does not expose feature importances."}</p>
                )}
                {record.features && (
                  <details>
                    <summary>All {Object.keys(record.features).length} model features for this record</summary>
                    <div style={{ maxHeight: 280, overflow: "auto" }}>
                      <table className="data">
                        <tbody>
                          {Object.entries(record.features).map(([k, v]) => (
                            <tr key={k}><td>{k}</td><td className="num mono">{fmtFeatureValue(v)}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
