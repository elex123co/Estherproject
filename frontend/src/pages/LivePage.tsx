import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, ApiError } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useLiveStream } from "../hooks/useLiveStream";
import { useHealthState } from "../context/HealthContext";
import { RecordDrawer } from "../components/RecordDrawer";
import { Banner, Card, Empty, ErrorBox, Loading, RiskBadge, StatCard } from "../components/ui";
import { fmtInt, fmtPct } from "../utils/format";
import type { RtPhase, RtPhaseSpec, RtScenario, RtScenarios, RtSnapshot } from "../types/api";

type Mode = "simulation" | "replay" | "live";

const MODE_TEXT: Record<Mode, string> = {
  simulation: "Controlled simulation",
  replay: "Replay uploaded capture",
  live: "External feed",
};

function fmtMs(x: number | null | undefined) {
  return x === null || x === undefined ? "n/a" : x < 10 ? `${x.toFixed(1)} ms` : `${Math.round(x)} ms`;
}

export function LivePage() {
  const { snap, feed, connected } = useLiveStream();
  const { data: catalog, error: catErr, reload } = useAsync(() => api.rtScenarios(), [snap?.state === "running"]);
  const [openId, setOpenId] = useState<string | null>(null);
  const running = snap?.state === "running";

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Live detection</h1>
          <p>
            Flows are scored by the trained model within about a tenth of a second of arriving. In simulation mode the traffic is
            composed in memory from held-out labelled flows; nothing is sent over any network.
          </p>
        </div>
        <span className={`tag ${connected ? "tag-normal" : "tag-suspicious"}`}>{connected ? "Stream connected" : "Stream disconnected, retrying"}</span>
      </div>

      {catErr && <ErrorBox error={catErr} onRetry={reload} />}
      {!snap && !catErr && <Loading label="Connecting to the detection engine" />}
      {snap && !snap.simulator.available && (
        <Banner tone="warn">
          <div><strong>Simulation pool unavailable.</strong> {snap.simulator.error ?? "Train a model to build it."} Replay and external-feed sessions still work.</div>
        </Banner>
      )}

      {snap && catalog && <Controls snap={snap} catalog={catalog} onChanged={reload} />}

      {snap && snap.state !== "idle" && snap.session && snap.totals && (
        <>
          {snap.session.error && <Banner tone="error"><div><strong>Session failed.</strong> {snap.session.error}</div></Banner>}
          {snap.state !== "running" && !snap.session.error && (
            <Banner tone="info">
              <div>
                Session {snap.state}: {snap.session.stop_reason}. {fmtInt(snap.totals.flows)} flows were stored as an analysis and can be reviewed under Alerts and review or exported from Reports.
              </div>
            </Banner>
          )}

          <div className="grid c5">
            <StatCard label="Flows scored" value={fmtInt(snap.totals.flows)} hint={running ? `${fmtInt(Math.round(snap.rate))} flows/s now` : `${snap.session.elapsed_s.toFixed(1)} s elapsed`} />
            <StatCard label="Flagged suspicious" value={fmtInt(snap.totals.suspicious)} tone="danger" hint="Potential intrusions, not confirmed" />
            <StatCard label="Require review" value={fmtInt(snap.totals.needs_review)} tone="review" hint="Uncertain or incomplete" />
            <StatCard label="Latency (median)" value={fmtMs(snap.latency_ms?.p50)} hint={snap.latency_ms ? `p95 ${fmtMs(snap.latency_ms.p95)}, max ${fmtMs(snap.latency_ms.max)}. Arrival to prediction, includes batch wait.` : undefined} />
            <StatCard label="Model processing" value={snap.processing_ms ? fmtMs(snap.processing_ms.mean) : "n/a"} hint="Mean time per micro-batch" />
          </div>

          <Card title="Traffic per second" subtitle={`${snap.session.name} (${MODE_TEXT[snap.session.mode]})`}>
            <LiveChart snap={snap} />
          </Card>

          {snap.phases.length > 0 && <Card title="Scenario timeline" subtitle="What the simulator injected, and how quickly the model reacted"><Phases snap={snap} /></Card>}

          <div className="grid c-2-1">
            <Card title="Live alert feed" subtitle="Flagged or uncertain flows, newest first. Click one to inspect." flush scroll>
              {feed.length === 0 ? (
                <Empty title={running ? "Nothing flagged yet" : "Nothing was flagged"}>Alerts appear here as the model flags flows.</Empty>
              ) : (
                <table className="data live-feed">
                  <thead><tr><th>Time</th><th>Source</th><th>Predicted</th><th className="num">Conf.</th><th>Risk</th>{snap.truth && <th>Truth</th>}</tr></thead>
                  <tbody>
                    {feed.slice(0, 60).map((a) => (
                      <tr key={a.id} className="clickable" onClick={() => setOpenId(a.id)}>
                        <td className="mono nowrap">{a.time.slice(11, 23)}</td>
                        <td className="mono small">{a.src_ip ?? "-"}</td>
                        <td>{a.predicted_class}</td>
                        <td className="num">{a.confidence === null ? "n/a" : fmtPct(a.confidence, 0)}</td>
                        <td><RiskBadge level={a.risk_level} /></td>
                        {snap.truth && <td className="small">{a.truth_label ?? "-"}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <Card title="Detection accuracy so far" subtitle={snap.truth ? "Against labels the source knew; the model never sees them" : undefined}>
              {snap.truth ? <Truth snap={snap} /> : <Empty title="No ground truth">This source carries no labels, so only predictions and risk are shown. Accuracy is not claimed.</Empty>}
            </Card>
          </div>
        </>
      )}

      {snap?.state === "idle" && <Card><Empty title="No session running">Choose a source above and start a session.</Empty></Card>}
      {openId && <RecordDrawer recordId={openId} onClose={() => setOpenId(null)} onChanged={() => undefined} />}
    </>
  );
}

function Truth({ snap }: { snap: RtSnapshot }) {
  const t = snap.truth!;
  return (
    <div className="stack">
      <dl className="kv">
        <dt>Attack recall</dt><dd>{fmtPct(t.recall, 1)}</dd>
        <dt>Attack precision</dt><dd>{fmtPct(t.precision, 1)}</dd>
        <dt>False-positive rate</dt><dd>{fmtPct(t.false_positive_rate, 2)}</dd>
        <dt>Caught / missed attacks</dt><dd>{fmtInt(t.tp)} / {fmtInt(t.fn)}</dd>
        <dt>False alarms / correct normal</dt><dd>{fmtInt(t.fp)} / {fmtInt(t.tn)}</dd>
      </dl>
      <p className="faint small" style={{ margin: 0 }}>
        Simulated flows come from a limited held-out pool that is sampled repeatedly, so these figures are a demonstration of the pipeline, not a field accuracy estimate.
      </p>
    </div>
  );
}

function LiveChart({ snap }: { snap: RtSnapshot }) {
  const data = snap.series;
  const running = snap.state === "running";
  const phases = snap.phases;
  return (
    <div style={{ height: 240 }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(v) => `${v}s`} />
          <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 11 }} width={44} />
          <Tooltip contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--border-strong)", borderRadius: 6 }} labelFormatter={(v) => `t = ${v}s`} />
          {phases.map((p) => (
            <ReferenceArea key={p.idx} x1={p.start} x2={p.start + p.duration} fill="var(--risk-high)" fillOpacity={0.07} />
          ))}
          <Area dataKey="normal" name="Classified normal" stackId="a" stroke="var(--risk-none)" fill="var(--risk-none)" fillOpacity={0.25} isAnimationActive={false} />
          <Area dataKey="suspicious" name="Flagged suspicious" stackId="a" stroke="var(--risk-critical)" fill="var(--risk-critical)" fillOpacity={0.45} isAnimationActive={false} />
          {running && data.length > 0 && <ReferenceLine x={data[data.length - 1].t} stroke="var(--accent)" strokeDasharray="3 3" />}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function Phases({ snap }: { snap: RtSnapshot }) {
  const total = snap.session?.duration_s ?? Math.max(...snap.phases.map((p) => p.start + p.duration));
  const now = Math.min(snap.session?.elapsed_s ?? 0, total);
  return (
    <div className="stack">
      <div className="timeline" aria-label="Scenario timeline">
        {snap.phases.map((p) => (
          <div key={p.idx} className={`tl-phase ${p.status}`} style={{ left: `${(p.start / total) * 100}%`, width: `${(p.duration / total) * 100}%` }} title={p.label}>
            {p.label}
          </div>
        ))}
        <div className="tl-now" style={{ left: `${(now / total) * 100}%` }} />
      </div>
      <table className="data">
        <thead><tr><th>Injected</th><th className="num">Window</th><th className="num">Rate</th><th>Status</th><th className="num">Flows</th><th className="num">Flagged</th><th className="num">Detection rate</th><th className="num">Time to first detection</th></tr></thead>
        <tbody>
          {snap.phases.map((p: RtPhase) => (
            <tr key={p.idx}>
              <td>{p.label}</td>
              <td className="num nowrap">{p.start}s to {p.start + p.duration}s</td>
              <td className="num">{p.rate}/s</td>
              <td>{p.status}</td>
              <td className="num">{fmtInt(p.flows ?? 0)}</td>
              <td className="num">{fmtInt(p.flagged ?? 0)}</td>
              <td className="num">{p.recall === null ? "n/a" : fmtPct(p.recall, 1)}</td>
              <td className="num">{p.first_detection_s === null || p.first_detection_s === undefined ? (p.status === "pending" ? "pending" : "not detected") : `${p.first_detection_s.toFixed(2)} s`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Controls({ snap, catalog, onChanged }: { snap: RtSnapshot; catalog: RtScenarios; onChanged: () => void }) {
  const { state: health } = useHealthState();
  const running = snap.state === "running";
  const [mode, setMode] = useState<Mode>(catalog.available ? "simulation" : "replay");
  const [presetIdx, setPresetIdx] = useState(0);
  const [sc, setSc] = useState<RtScenario | null>(catalog.presets[0]?.scenario ?? null);
  const [seed, setSeed] = useState(String(catalog.presets[0]?.scenario.seed ?? ""));
  const [replayId, setReplayId] = useState("");
  const [replayRate, setReplayRate] = useState(100);
  const [loop, setLoop] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | Error | null>(null);

  useEffect(() => {
    if (!sc && catalog.presets[0]) setSc(catalog.presets[0].scenario);
  }, [catalog, sc]);

  const ready = health.phase === "answered" && health.health.ready;
  const classes = useMemo(() => catalog.classes.filter((c) => c !== "BENIGN"), [catalog.classes]);

  const pickPreset = (i: number) => {
    setPresetIdx(i);
    setSc(catalog.presets[i].scenario);
    setSeed(String(catalog.presets[i].scenario.seed ?? ""));
  };
  const editPhase = (i: number, patch: Partial<RtPhaseSpec>) =>
    setSc((s) => (s ? { ...s, phases: s.phases.map((p, j) => (j === i ? { ...p, ...patch } : p)) } : s));

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (mode === "simulation" && sc) {
        await api.rtStart({ mode, scenario: { ...sc, seed: seed.trim() === "" ? null : Number(seed) } });
      } else if (mode === "replay") {
        await api.rtStart({ mode, replay: { scan_id: replayId, rate: replayRate, loop }, max_duration_seconds: 300 });
      } else if (mode === "live") {
        await api.rtStart({ mode, max_duration_seconds: 600 });
      }
      onChanged();
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(false);
    }
  };
  const stop = async () => {
    setBusy(true);
    try {
      await api.rtStop();
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(false);
    }
  };

  if (running) {
    return (
      <Card title={`Running: ${snap.session?.name}`} subtitle={snap.session?.description ?? undefined}
        actions={<button className="btn danger" disabled={busy} onClick={stop}>Stop session</button>}>
        <p className="muted small" style={{ margin: 0 }}>
          {snap.session?.mode === "live"
            ? "Waiting for flows posted to POST /api/realtime/ingest. Each flow is scored on arrival."
            : "Everything on this page is computed from the running session."}
        </p>
      </Card>
    );
  }

  return (
    <Card title="Start a session" subtitle="One session runs at a time. Results are saved as an analysis you can review afterwards.">
      <div className="stack">
        <div className="seg" role="tablist">
          {(Object.keys(MODE_TEXT) as Mode[]).map((m) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)} disabled={m === "simulation" && !catalog.available}>{MODE_TEXT[m]}</button>
          ))}
        </div>

        {mode === "simulation" && sc && (
          <>
            <Banner tone="info"><div>{catalog.note}</div></Banner>
            <div className="row">
              <label className="field">Preset
                <select value={presetIdx} onChange={(e) => pickPreset(Number(e.target.value))}>
                  {catalog.presets.map((p, i) => <option key={p.name} value={i}>{p.name}</option>)}
                </select>
              </label>
              <label className="field">Duration (s)
                <input type="number" min={5} max={catalog.limits.max_seconds} value={sc.duration_seconds} onChange={(e) => setSc({ ...sc, duration_seconds: Number(e.target.value) })} />
              </label>
              <label className="field">Normal flows/s
                <input type="number" min={0} max={catalog.limits.max_rate} value={sc.baseline_rate} onChange={(e) => setSc({ ...sc, baseline_rate: Number(e.target.value) })} />
              </label>
              <label className="field">Seed (optional)
                <input type="text" inputMode="numeric" placeholder="random" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} />
              </label>
            </div>
            <p className="muted small" style={{ margin: 0 }}>{catalog.presets[presetIdx]?.description} The same seed reproduces the same traffic.</p>
            <table className="data">
              <thead><tr><th>Injected attack class</th><th className="num">Start (s)</th><th className="num">Length (s)</th><th className="num">Flows/s</th><th /></tr></thead>
              <tbody>
                {sc.phases.map((p, i) => (
                  <tr key={i}>
                    <td><select value={p.label} onChange={(e) => editPhase(i, { label: e.target.value })}>{classes.map((c) => <option key={c}>{c}</option>)}</select></td>
                    <td className="num"><input type="number" min={0} value={p.start} onChange={(e) => editPhase(i, { start: Number(e.target.value) })} /></td>
                    <td className="num"><input type="number" min={1} value={p.duration} onChange={(e) => editPhase(i, { duration: Number(e.target.value) })} /></td>
                    <td className="num"><input type="number" min={1} max={catalog.limits.max_rate} value={p.rate} onChange={(e) => editPhase(i, { rate: Number(e.target.value) })} /></td>
                    <td><button className="btn sm ghost" onClick={() => setSc({ ...sc, phases: sc.phases.filter((_, j) => j !== i) })}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="row">
              <button className="btn sm" disabled={classes.length === 0 || sc.phases.length >= 20}
                onClick={() => setSc({ ...sc, phases: [...sc.phases, { label: classes[0], start: 0, duration: 10, rate: 50 }] })}>Add attack phase</button>
              <span className="faint small">Available classes come from the held-out pool: {classes.join(", ") || "none"}.</span>
            </div>
          </>
        )}

        {mode === "replay" && (
          catalog.replayable_scans.length === 0 ? (
            <Empty title="No uploaded captures">Upload a CSV on the Upload page first, then replay it here at a chosen rate.</Empty>
          ) : (
            <div className="row">
              <label className="field">Uploaded file
                <select value={replayId} onChange={(e) => setReplayId(e.target.value)}>
                  <option value="">Choose a file</option>
                  {catalog.replayable_scans.map((s) => <option key={s.id} value={s.id}>{s.filename} ({fmtInt(s.rows)} rows)</option>)}
                </select>
              </label>
              <label className="field">Flows/s
                <input type="number" min={1} max={catalog.limits.max_rate} value={replayRate} onChange={(e) => setReplayRate(Number(e.target.value))} />
              </label>
              <label className="field">Loop
                <select value={loop ? "y" : "n"} onChange={(e) => setLoop(e.target.value === "y")}><option value="n">Once</option><option value="y">Until stopped</option></select>
              </label>
            </div>
          )
        )}

        {mode === "live" && (
          <p className="muted small" style={{ margin: 0 }}>
            Opens a session that scores flow records posted by your own collector to <span className="mono">POST /api/realtime/ingest</span> (up to 500 per request,
            using the model's feature names). Packet capture and flow extraction are done outside this application.
          </p>
        )}

        {err && <ErrorBox error={err} />}
        <div className="row">
          <button className="btn primary" disabled={busy || !ready || (mode === "replay" && !replayId) || (mode === "simulation" && !sc)} onClick={start}>Start session</button>
          {!ready && <span className="faint small">The model or database is not ready.</span>}
        </div>
      </div>
    </Card>
  );
}
