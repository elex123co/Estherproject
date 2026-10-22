import { useState } from "react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { ImportanceBars } from "../components/charts";
import { Banner, Card, ErrorBox, Loading, StatCard } from "../components/ui";
import type { EvalMetrics } from "../types/api";
import { fmtDateTime, fmtInt, fmtNum, fmtPct, titleCase } from "../utils/format";

export function ModelPage() {
  const model = useAsync(() => api.model(), []);
  const evaluation = useAsync(() => api.evaluation(), []);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Model performance</h1>
          <p>Measured results for the deployed model. Figures come from data the model did not train on, as labelled below.</p>
        </div>
      </div>

      {(model.loading || evaluation.loading) && !model.data && <Loading />}
      {model.error && <ErrorBox error={model.error} onRetry={model.reload} />}
      {evaluation.error && evaluation.error.message !== model.error?.message && <ErrorBox error={evaluation.error} onRetry={evaluation.reload} />}

      {model.data?.dataset.is_synthetic && (
        <Banner tone="warn"><div><strong>Synthetic data.</strong> This model was trained and evaluated on generated smoke-test data. The numbers below prove the pipeline runs end to end. They are not evidence of detection quality on real traffic.</div></Banner>
      )}

      {model.data && (
        <>
          <div className="grid c2">
            <Card title="Deployed model">
              <dl className="kv">
                <dt>Algorithm</dt><dd>{titleCase(model.data.model_type)}</dd>
                <dt>Version</dt><dd className="mono">{model.data.model_version}</dd>
                <dt>Trained</dt><dd>{fmtDateTime(model.data.trained_at)} ({model.data.training_seconds}s, seed {model.data.random_seed})</dd>
                <dt>Selection</dt><dd>{model.data.selection_criterion}</dd>
                <dt>Features</dt><dd>{model.data.features_count}</dd>
                <dt>Classes</dt><dd>{model.data.classes.map((c) => <span className="chip" key={c}>{c}</span>)}</dd>
                <dt>Confidence</dt><dd className="small">{model.data.confidence_note}</dd>
              </dl>
            </Card>
            <Card title="Training data and split">
              <dl className="kv">
                <dt>Dataset</dt><dd>{model.data.dataset.name}{model.data.dataset.version ? ` (${model.data.dataset.version})` : ""}</dd>
                <dt>Rows</dt><dd>{fmtInt(model.data.dataset.rows_loaded)} loaded, {fmtInt(model.data.dataset.duplicates_removed)} duplicates removed, {fmtInt(model.data.dataset.rows_used)} used{model.data.dataset.max_rows_sampling ? ` (stratified sample, max ${fmtInt(model.data.dataset.max_rows_sampling)})` : ""}</dd>
                <dt>Split</dt><dd>{model.data.split.strategy}: train {fmtInt(model.data.split.train_rows)}, validation {fmtInt(model.data.split.validation_rows)}, test {fmtInt(model.data.split.test_rows)}</dd>
                <dt>Preprocessing</dt><dd><ul style={{ margin: 0, paddingLeft: 16 }}>{model.data.preprocessing.map((p) => <li key={p}>{p}</li>)}</ul></dd>
                {Object.keys(model.data.dataset.classes_dropped_too_few_samples).length > 0 && (
                  <><dt>Dropped classes</dt><dd>{Object.entries(model.data.dataset.classes_dropped_too_few_samples).map(([k, v]) => `${k} (${v} rows)`).join(", ")}: too few samples to split reliably</dd></>
                )}
              </dl>
              <p className="faint small" style={{ margin: "8px 0 0" }}>{model.data.split.caveat}</p>
            </Card>
          </div>

          <Card title="Candidate comparison" subtitle="All three were trained on the same split. Selection used the validation split only, so the test split stays unseen." flush scroll>
            <table className="data">
              <thead><tr><th>Model</th><th className="num">Macro F1</th><th className="num">Macro precision</th><th className="num">Macro recall</th><th className="num">Accuracy</th><th className="num">Attack recall</th><th className="num">False-positive rate</th><th className="num">Fit time</th></tr></thead>
              <tbody>
                {Object.entries(model.data.candidates).map(([name, c]) => (
                  <tr key={name}>
                    <td>{titleCase(name)} {name === model.data!.model_type && <span className="badge status-completed">selected</span>}</td>
                    <td className="num">{fmtNum(c.validation.macro_f1)}</td>
                    <td className="num">{fmtNum(c.validation.macro_precision)}</td>
                    <td className="num">{fmtNum(c.validation.macro_recall)}</td>
                    <td className="num">{fmtNum(c.validation.accuracy)}</td>
                    <td className="num">{fmtPct(c.validation.attack_recall, 2)}</td>
                    <td className="num">{fmtPct(c.validation.false_positive_rate, 2)}</td>
                    <td className="num">{c.fit_seconds}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="faint small" style={{ padding: "8px 14px 12px", margin: 0 }}>Validation split figures. Attack recall and false-positive rate treat any attack class as the positive class.</p>
          </Card>
        </>
      )}

      {evaluation.data && <Metrics m={evaluation.data.selected} title={`Selected model: ${titleCase(evaluation.data.selected_model)}`} />}

      {model.data?.feature_importances && (
        <Card title="Most important features" subtitle="Model-wide importance (impurity based). Shows what the model relies on overall, not why a single record was flagged.">
          <ImportanceBars data={model.data.feature_importances} />
        </Card>
      )}
    </>
  );
}

export function Metrics({ m, title }: { m: EvalMetrics; title: string }) {
  const b = m.binary_detection;
  return (
    <>
      <Banner tone="info">
        <div><strong>{title}.</strong> Evaluated on: <strong>{m.basis}</strong> ({fmtInt(m.n_samples)} records).{m.caveat && <> {m.caveat}</>}</div>
      </Banner>

      <h2>Attack vs normal</h2>
      <div className="grid c5">
        <StatCard label="Precision" value={fmtPct(b.precision, 2)} hint="Flagged records that were attacks" />
        <StatCard label="Recall" value={fmtPct(b.recall, 2)} hint="Attacks that were caught" />
        <StatCard label="F1-score" value={fmtPct(b.f1, 2)} />
        <StatCard label="False-positive rate" value={fmtPct(b.false_positive_rate, 3)} tone="warn" hint={`${fmtInt(b.false_positives)} normal flows flagged`} />
        <StatCard label="Missed attacks" value={fmtInt(b.false_negatives)} tone="danger" hint={`False-negative rate ${fmtPct(b.false_negative_rate, 2)}`} />
      </div>

      <h2>All classes</h2>
      <div className="grid c4">
        <StatCard label="Macro F1" value={fmtNum(m.macro_avg.f1)} hint="Every class counts equally" />
        <StatCard label="Macro precision" value={fmtNum(m.macro_avg.precision)} />
        <StatCard label="Macro recall" value={fmtNum(m.macro_avg.recall)} />
        <StatCard label="Accuracy" value={fmtPct(m.accuracy, 2)} hint="Secondary: dominated by the majority class" />
      </div>
      <p className="muted small" style={{ margin: 0 }}>{m.averaging_note} Weighted F1: {fmtNum(m.weighted_avg.f1)}.</p>

      <Card title="Per-class results" subtitle="Minority attack classes matter most. Check support before trusting a number." flush scroll>
        <table className="data">
          <thead><tr><th>Class</th><th className="num">Precision</th><th className="num">Recall</th><th className="num">F1</th><th className="num">Support</th></tr></thead>
          <tbody>
            {m.per_class.map((c) => (
              <tr key={c.label}>
                <td>{c.label}</td>
                <td className="num">{fmtNum(c.precision)}</td><td className="num">{fmtNum(c.recall)}</td><td className="num">{fmtNum(c.f1)}</td>
                <td className="num">{fmtInt(c.support)}{c.support > 0 && c.support < 30 && <span className="badge risk-Medium" style={{ marginLeft: 6 }} title="Very few samples. This score is unreliable.">low support</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <ConfusionMatrix m={m} />
    </>
  );
}

function ConfusionMatrix({ m }: { m: EvalMetrics }) {
  const [mode, setMode] = useState<"counts" | "rows">("rows");
  const totals = m.confusion_matrix.map((r) => r.reduce((a, b) => a + b, 0));
  return (
    <Card
      title="Confusion matrix"
      subtitle="Rows are the true class, columns are the predicted class. Teal outlines mark correct predictions."
      actions={<div className="seg"><button className={mode === "rows" ? "on" : ""} onClick={() => setMode("rows")}>Row %</button><button className={mode === "counts" ? "on" : ""} onClick={() => setMode("counts")}>Counts</button></div>}
    >
      <div className="matrix-wrap">
        <table className="matrix">
          <thead>
            <tr><th />{m.labels.map((l) => <th key={l} title={l} style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", height: 120 }}>{l}</th>)}</tr>
          </thead>
          <tbody>
            {m.confusion_matrix.map((row, i) => (
              <tr key={m.labels[i]}>
                <th className="rowh">{m.labels[i]}</th>
                {row.map((v, j) => {
                  const frac = totals[i] ? v / totals[i] : 0;
                  const diag = i === j;
                  const alpha = v === 0 ? 0 : Math.min(0.9, 0.12 + frac * 0.85);
                  const bg = v === 0 ? "transparent" : diag ? `rgba(76,194,217,${alpha})` : `rgba(239,79,95,${Math.min(0.9, 0.25 + frac * 1.5)})`;
                  return (
                    <td key={j} className={diag ? "diag" : ""} style={{ background: bg }} title={`${m.labels[i]} predicted as ${m.labels[j]}: ${v} (${(frac * 100).toFixed(2)}% of the row)`}>
                      {v === 0 ? <span className="faint">0</span> : mode === "counts" ? v.toLocaleString() : `${(frac * 100).toFixed(frac < 0.1 && frac > 0 ? 1 : 0)}%`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
