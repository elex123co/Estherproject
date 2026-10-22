import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { Card, ErrorBox, Loading, RiskBadge } from "../components/ui";

export function RiskRulesPage() {
  const { data, error, loading, reload } = useAsync(() => api.riskRules(), []);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Risk rules</h1>
          <p>
            The risk level is assigned by transparent rules, separately from the model. Severity comes from the predicted attack category, may be raised only by
            explicit evidence-based escalation rules, and is never derived from model confidence alone. Edit <code>backend/app/risk/rules.json</code> and restart the API to change them.
          </p>
        </div>
      </div>
      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && (
        <>
          <Card title={`Rule set v${data.version}`}>
            <dl className="kv">
              <dt>Low-confidence threshold</dt><dd>{data.low_confidence_threshold}: below this, a suspicious record is capped at <strong>{data.confidence_cap_level}</strong> and marked as requiring review</dd>
              <dt>Uncertain normal threshold</dt><dd>{data.benign_review_confidence_below}: a normal prediction below this is shown as "Needs review" instead of clean</dd>
              <dt>Max imputed fraction</dt><dd>{data.max_imputed_fraction}: records with more missing or invalid features than this require review</dd>
              <dt>Unmapped categories</dt><dd><RiskBadge level={data.default_rule.level} /> {data.default_rule.reason}</dd>
            </dl>
          </Card>
          <Card title="Category rules" flush scroll>
            <table className="data">
              <thead><tr><th>Predicted category</th><th>Risk level</th><th>Rule</th><th>Rationale</th></tr></thead>
              <tbody>
                {Object.entries(data.category_rules).map(([cat, rule]) => (
                  <tr key={cat}><td>{cat}</td><td><RiskBadge level={rule.level} /></td><td className="mono small">{rule.rule_id}</td><td className="small">{rule.reason}</td></tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Card title="Escalation rules" subtitle="Raise severity only when the model is confident AND the record itself shows supporting evidence" flush scroll>
            <table className="data">
              <thead><tr><th>Rule</th><th>Applies to</th><th>Requires</th><th>Raises to</th></tr></thead>
              <tbody>
                {data.escalations.map((e) => (
                  <tr key={e.rule_id}>
                    <td><span className="mono small">{e.rule_id}</span><div className="muted small">{e.description}</div></td>
                    <td className="small">{e.categories.join(", ")}</td>
                    <td className="small">Confidence &ge; {e.min_confidence}; {e.conditions.map((c) => `${c.feature} ${c.op} ${c.value.toLocaleString()}`).join(" and ")}</td>
                    <td><RiskBadge level={e.raise_to} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </>
  );
}
