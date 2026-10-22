import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useHealthState } from "../context/HealthContext";
import { useScope } from "../context/ScanContext";
import { RecordDrawer } from "../components/RecordDrawer";
import { Banner, Card, ClassBadge, ErrorBox, Loading, RiskBadge, StatCard, StatusBadge } from "../components/ui";
import type { Scan, UploadResponse, Validation } from "../types/api";
import { fmtBytes, fmtDateTime, fmtInt, fmtPct } from "../utils/format";

type Phase = "idle" | "uploading" | "validated" | "rejected" | "analyzing" | "done" | "failed";

export function UploadPage() {
  const { ready } = useHealthState();
  const { scans, refreshScans, setScanId } = useScope();
  const schema = useAsync(() => api.schema(), [ready]);

  const [phase, setPhase] = useState<Phase>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [uploadFraction, setUploadFraction] = useState(0);
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setPhase("idle"); setFile(null); setUpload(null); setError(null); setScan(null); setUploadFraction(0);
    if (inputRef.current) inputRef.current.value = "";
  };

  const choose = (f: File | null) => {
    if (!f) return;
    setFile(f); setError(null); setUpload(null); setScan(null);
    void send(f);
  };

  async function send(f: File) {
    setPhase("uploading");
    setUploadFraction(0);
    try {
      const res = await api.upload(f, setUploadFraction);
      setUpload(res);
      setPhase(res.validation.compatible && res.scan_id ? "validated" : "rejected");
    } catch (e) {
      setError(e as Error);
      setPhase("idle");
    }
  }

  async function start(scanId: string) {
    setError(null);
    try {
      const s = await api.startAnalysis(scanId);
      setScan(s);
      setPhase("analyzing");
      refreshScans();
    } catch (e) {
      setError(e as Error);
    }
  }

  // Poll the running job.
  const scanId = scan?.id;
  useEffect(() => {
    if (phase !== "analyzing" || !scanId) return;
    const timer = window.setInterval(() => {
      api.scan(scanId).then((s) => {
        setScan(s);
        if (s.status === "completed") { setPhase("done"); refreshScans(); }
        if (s.status === "failed") { setPhase("failed"); refreshScans(); }
      }).catch((e: Error) => { setError(e); });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [phase, scanId, refreshScans]);

  const progress = scan && scan.rows_total ? Math.min(1, scan.rows_processed / scan.rows_total) : 0;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Upload and analyze</h1>
          <p>Upload a CSV of network flows. The file is validated against the model's feature schema before anything is analyzed.</p>
        </div>
      </div>

      {!ready && <Banner tone="error"><div>The backend or model is not ready, so uploads are disabled. See the system status panel.</div></Banner>}

      <div className="grid c-2-1">
        <div className="stack">
          <Card title="1. Choose a file">
            <div
              className={`dropzone ${drag ? "drag" : ""}`}
              role="button"
              tabIndex={0}
              aria-label="Choose a CSV file to upload"
              onClick={() => ready && inputRef.current?.click()}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && ready && inputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); if (ready) choose(e.dataTransfer.files?.[0] ?? null); }}
              style={ready ? undefined : { opacity: 0.5, cursor: "not-allowed" }}
            >
              <strong>{file ? file.name : "Drop a .csv file here, or click to browse"}</strong>
              <div className="muted small" style={{ marginTop: 4 }}>
                {file ? fmtBytes(file.size) : `Up to ${schema.data?.max_upload_mb ?? 200} MB. One network flow per row, with a header row.`}
              </div>
              <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => choose(e.target.files?.[0] ?? null)} />
            </div>
            {phase === "uploading" && (
              <div style={{ marginTop: 12 }}>
                <div className="progress" role="progressbar" aria-valuenow={Math.round(uploadFraction * 100)} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${uploadFraction * 100}%` }} /></div>
                <div className="muted small" style={{ marginTop: 4 }}>
                  {uploadFraction < 1 ? `Uploading ${Math.round(uploadFraction * 100)}%` : "Validating the whole file (this can take a moment for large files)..."}
                </div>
              </div>
            )}
            {error && phase !== "analyzing" && <div style={{ marginTop: 12 }}><ErrorBox error={error} /></div>}
          </Card>

          {upload && (
            <Card title="2. Validation results" subtitle={`${upload.filename} (${fmtBytes(upload.size_bytes)})`}>
              <ValidationReport v={upload.validation} />
              {phase === "validated" && upload.scan_id && (
                <div className="row" style={{ marginTop: 14 }}>
                  <button className="btn primary" onClick={() => start(upload.scan_id!)}>Start analysis of {fmtInt(upload.validation.rows)} records</button>
                  <button className="btn" onClick={reset}>Discard</button>
                </div>
              )}
              {phase === "rejected" && (
                <div className="row" style={{ marginTop: 14 }}>
                  <Banner tone="error"><div><strong>This file cannot be analyzed.</strong> No copy was kept. Fix the issues above and upload it again.</div></Banner>
                  <button className="btn" onClick={reset}>Try another file</button>
                </div>
              )}
            </Card>
          )}

          {(phase === "analyzing" || phase === "done" || phase === "failed") && scan && (
            <Card title="3. Analysis" actions={<StatusBadge status={scan.status} />}>
              {(phase === "analyzing") && (
                <>
                  <div className="progress" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${progress * 100}%` }} /></div>
                  <div className="muted small" style={{ marginTop: 6 }}>
                    {scan.status === "queued" ? "Queued, waiting for a worker..." : `Analyzed ${fmtInt(scan.rows_processed)} of ${fmtInt(scan.rows_total)} records (${Math.round(progress * 100)}%)`}
                  </div>
                  {error && <div style={{ marginTop: 8 }}><ErrorBox error={error} /></div>}
                </>
              )}
              {phase === "failed" && <Banner tone="error"><div><strong>Analysis failed.</strong> {scan.error ?? "Unknown error."} Partial results were discarded.</div></Banner>}
              {phase === "done" && scan.summary && (
                <div className="stack">
                  <div className="grid c3">
                    <StatCard label="Records analyzed" value={fmtInt(scan.summary.records_analyzed)} hint={`${scan.summary.duration_seconds ?? "-"} s`} />
                    <StatCard label="Flagged suspicious" value={fmtInt(scan.suspicious_records)} tone="danger" />
                    <StatCard label="Require review" value={fmtInt(scan.records_requiring_review)} tone="review" />
                  </div>
                  {scan.summary.label_comparison && (
                    <p className="muted small" style={{ margin: 0 }}>
                      The file contained labels. Compared with them, attack-vs-normal recall is {fmtPct(scan.summary.label_comparison.binary_detection.recall)} and false-positive rate is {fmtPct(scan.summary.label_comparison.binary_detection.false_positive_rate)}.
                      This is not the held-out test evaluation and is optimistic if the file overlaps the training data.
                    </p>
                  )}
                  <div className="row">
                    <Link className="btn primary" to="/alerts" onClick={() => setScanId(scan.id)}>Review alerts</Link>
                    <Link className="btn" to="/" onClick={() => setScanId(scan.id)}>View overview</Link>
                    <Link className="btn" to="/reports">Generate report</Link>
                    <button className="btn ghost" onClick={reset}>Analyze another file</button>
                  </div>
                </div>
              )}
            </Card>
          )}

          <SingleRecordCard disabled={!ready} onDone={refreshScans} />
        </div>

        <div className="stack">
          <Card title="Expected data format">
            {schema.loading && !schema.data && <Loading />}
            {schema.error && <ErrorBox error={schema.error} onRetry={schema.reload} />}
            {schema.data && (
              <div className="stack">
                <p className="small" style={{ margin: 0 }}>{schema.data.format}. Trained on <strong>{schema.data.training_dataset ?? "unknown dataset"}</strong>.</p>
                <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
                  {schema.data.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
                <dl className="kv" style={{ gridTemplateColumns: "100px 1fr" }}>
                  {Object.entries(schema.data.optional_columns).map(([k, v]) => (<Fragment key={k}><dt>{k}</dt><dd className="small">{v}</dd></Fragment>))}
                </dl>
                <details>
                  <summary>{schema.data.required_features.length} required feature columns</summary>
                  <div style={{ maxHeight: 260, overflow: "auto" }}>
                    {schema.data.required_features.map((f) => <span key={f} className="chip">{f}</span>)}
                  </div>
                </details>
              </div>
            )}
          </Card>
        </div>
      </div>

      <Card title="Analysis history" flush scroll>
        <table className="data">
          <thead><tr><th>Source</th><th>Status</th><th className="num">Records</th><th className="num">Flagged</th><th>Created</th><th>Model</th><th></th></tr></thead>
          <tbody>
            {scans.length === 0 && <tr><td colSpan={7} className="muted" style={{ textAlign: "center", padding: 24 }}>No analyses yet.</td></tr>}
            {scans.map((s) => (
              <tr key={s.id}>
                <td>{s.filename ?? "Single record"}</td>
                <td><StatusBadge status={s.status} />{s.error && <div className="small" style={{ color: "#ff9aa4" }}>{s.error}</div>}</td>
                <td className="num">{fmtInt(s.records_stored || s.rows_total)}</td>
                <td className="num">{fmtInt(s.suspicious_records)}</td>
                <td className="nowrap">{fmtDateTime(s.created_at)}</td>
                <td className="mono small">{s.model_version?.slice(0, 24) ?? "-"}</td>
                <td className="right nowrap">
                  {s.status === "uploaded" && <button className="btn sm primary" onClick={() => { setPhase("analyzing"); void start(s.id); }}>Analyze</button>}{" "}
                  {s.status !== "running" && s.status !== "queued" && <DeleteButton id={s.id} onDone={() => { refreshScans(); }} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

function DeleteButton({ id, onDone }: { id: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="btn sm danger"
      disabled={busy}
      onClick={async () => {
        if (!window.confirm("Delete this analysis and all of its stored records? This cannot be undone.")) return;
        setBusy(true);
        try { await api.deleteScan(id); onDone(); } catch (e) { window.alert((e as Error).message); } finally { setBusy(false); }
      }}
    >Delete</button>
  );
}

function ValidationReport({ v }: { v: Validation }) {
  return (
    <div className="stack">
      {v.errors.map((e, i) => <Banner key={i} tone="error"><div><strong>Incompatible.</strong> {e}</div></Banner>)}
      {v.compatible && <Banner tone="ok"><div><strong>Compatible.</strong> All {v.features_expected} features the model needs were found.</div></Banner>}
      {v.warnings.map((w, i) => <Banner key={i} tone="warn"><div>{w}</div></Banner>)}
      <div className="grid c4">
        <StatCard label="Records" value={fmtInt(v.rows)} />
        <StatCard label="Features found" value={`${v.features_detected} / ${v.features_expected}`} tone={v.compatible ? "ok" : "danger"} />
        <StatCard label="Missing values" value={fmtInt(v.missing_values)} hint={`${fmtInt(v.invalid_values)} invalid or infinite`} />
        <StatCard label="Duplicate rows" value={fmtInt(v.duplicate_rows)} />
      </div>
      {v.missing_required_features.length > 0 && (
        <details open>
          <summary>{v.missing_required_features.length} missing features</summary>
          {v.missing_required_features.map((f) => <span key={f} className="chip">{f}</span>)}
        </details>
      )}
      {v.unexpected_columns.length > 0 && (
        <details>
          <summary>{v.unexpected_columns.length} columns not used by the model</summary>
          {v.unexpected_columns.map((f) => <span key={f} className="chip">{f}</span>)}
        </details>
      )}
      {v.label_distribution ? (
        <details>
          <summary>Label distribution in the file ({Object.keys(v.label_distribution).length} labels). These are supplied labels, not predictions.</summary>
          <table className="data"><tbody>
            {Object.entries(v.label_distribution).map(([k, n]) => <tr key={k}><td>{k}</td><td className="num">{fmtInt(n)}</td></tr>)}
          </tbody></table>
        </details>
      ) : <p className="muted small" style={{ margin: 0 }}>No Label column. Analysis can run, but results cannot be compared with ground truth.</p>}
    </div>
  );
}

function SingleRecordCard({ disabled, onDone }: { disabled: boolean; onDone: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const run = useCallback(async () => {
    setError(null); setResult(null);
    let parsed: unknown;
    try { parsed = JSON.parse(text); } catch { setError(new Error("That is not valid JSON.")); return; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) { setError(new Error("Provide a single JSON object: feature name to value.")); return; }
    setBusy(true);
    try { setResult(await api.predictRecord(parsed as Record<string, unknown>)); onDone(); }
    catch (e) { setError(e as Error); }
    finally { setBusy(false); }
  }, [text, onDone]);

  return (
    <Card title="Analyze a single record" subtitle="Paste one flow as a JSON object containing every required feature">
      <details>
        <summary>Show</summary>
        <div className="stack">
          <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder='{"Destination Port": 80, "Flow Duration": 1234, ...}' aria-label="Record JSON" />
          <div className="row"><button className="btn primary" disabled={disabled || busy || !text.trim()} onClick={run}>{busy ? "Analyzing..." : "Analyze record"}</button></div>
          {error && <ErrorBox error={error} />}
          {result && (
            <div className="panel">
              <div className="row" style={{ marginBottom: 6 }}>
                <strong>{String(result.predicted_class)}</strong>
                <ClassBadge suspicious={Boolean(result.is_suspicious)} />
                <RiskBadge level={String(result.risk_level)} />
              </div>
              <div className="muted small">{String(result.risk_reason)}</div>
              <div style={{ marginTop: 8 }}><button className="btn sm" onClick={() => setOpen(String(result.record_id))}>Open details</button></div>
            </div>
          )}
        </div>
      </details>
      {open && <RecordDrawer recordId={open} onClose={() => setOpen(null)} onChanged={() => undefined} />}
    </Card>
  );
}
