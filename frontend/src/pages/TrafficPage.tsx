import { useMemo, useState } from "react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useScope } from "../context/ScanContext";
import { CategoryBars, ClassificationDonut, RiskBars, TrendChart } from "../components/charts";
import { RecordDrawer } from "../components/RecordDrawer";
import { RecordsTable } from "../components/RecordsTable";
import { Banner, Card, Empty, ErrorBox, Loading, Pager } from "../components/ui";
import type { RecordQuery } from "../types/api";
import { localInputToIso } from "../utils/format";

const PAGE_SIZE = 20;

export function TrafficPage() {
  const { scanId } = useScope();
  const [classification, setClassification] = useState<"" | "normal" | "suspicious">("");
  const [category, setCategory] = useState("");
  const [risk, setRisk] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);

  const query: RecordQuery = useMemo(
    () => ({
      scan_id: scanId || undefined,
      classification,
      category: category || undefined,
      risk_level: risk || undefined,
      date_from: localInputToIso(from),
      date_to: localInputToIso(to),
    }),
    [scanId, classification, category, risk, from, to],
  );
  const key = JSON.stringify(query);

  const options = useAsync(() => api.filterOptions(scanId || undefined), [scanId]);
  const traffic = useAsync(() => api.traffic(query), [key]);
  const records = useAsync(() => api.records({ ...query, page, page_size: PAGE_SIZE }), [key, page]);

  const reset = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(1);
  };
  const filtersActive = Boolean(classification || category || risk || from || to);
  const t = traffic.data;
  const total = t ? t.classification.normal + t.classification.suspicious : 0;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Traffic analysis</h1>
          <p>Distributions and trends computed from stored predictions. Filters apply to every chart and to the record table.</p>
        </div>
      </div>

      <Card>
        <div className="filters">
          <label className="field">Classification
            <select value={classification} onChange={(e) => reset(setClassification)(e.target.value as "" | "normal" | "suspicious")}>
              <option value="">All</option><option value="normal">Normal</option><option value="suspicious">Suspicious</option>
            </select>
          </label>
          <label className="field">Predicted category
            <select value={category} onChange={(e) => reset(setCategory)(e.target.value)}>
              <option value="">All</option>
              {options.data?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="field">Risk level
            <select value={risk} onChange={(e) => reset(setRisk)(e.target.value)}>
              <option value="">All</option>
              {options.data?.risk_levels.map((r) => <option key={r} value={r}>{r === "None" ? "No risk rule (normal)" : r}</option>)}
            </select>
          </label>
          <label className="field">From
            <input type="datetime-local" value={from} onChange={(e) => reset(setFrom)(e.target.value)} />
          </label>
          <label className="field">To
            <input type="datetime-local" value={to} onChange={(e) => reset(setTo)(e.target.value)} />
          </label>
          {filtersActive && (
            <button className="btn" onClick={() => { setClassification(""); setCategory(""); setRisk(""); setFrom(""); setTo(""); setPage(1); }}>Clear filters</button>
          )}
        </div>
      </Card>

      {traffic.loading && !t && <Loading />}
      {traffic.error && <ErrorBox error={traffic.error} onRetry={traffic.reload} />}

      {t && total === 0 && (
        <Card>
          <Empty title={filtersActive ? "No records match these filters" : "No analysis results yet"}>
            {filtersActive ? "Widen or clear the filters." : "Charts appear after a dataset has been analyzed."}
          </Empty>
        </Card>
      )}

      {t && total > 0 && (
        <>
          <div className="grid c3">
            <Card title="Normal vs suspicious"><ClassificationDonut normal={t.classification.normal} suspicious={t.classification.suspicious} /></Card>
            <Card title="Risk levels" subtitle="Includes normal traffic as 'No risk rule'"><RiskBars counts={t.risk_levels} includeNone /></Card>
            <Card title="Predicted categories"><CategoryBars data={t.categories} /></Card>
          </div>

          <Card title="Trend over time" subtitle={`Records per ${t.trend_bucket}`}>
            {t.time_basis !== "flow_timestamp" && <Banner tone="warn"><div>{t.time_basis_note}</div></Banner>}
            {t.time_basis === "flow_timestamp" && <p className="muted small">{t.time_basis_note}</p>}
            <div style={{ marginTop: 8 }}>
              {t.trend.length > 0 ? <TrendChart data={t.trend} bucket={t.trend_bucket} /> : <Empty title="No time data" />}
            </div>
          </Card>
        </>
      )}

      <Card title="Records" subtitle="Click a row for the full prediction, risk reasoning and review controls" flush scroll>
        {records.loading && !records.data && <Loading />}
        {records.error && <div style={{ padding: 16 }}><ErrorBox error={records.error} onRetry={records.reload} /></div>}
        {records.data && records.data.items.length === 0 && <Empty title="No records to show" />}
        {records.data && records.data.items.length > 0 && (
          <>
            <RecordsTable items={records.data.items} onOpen={setOpen} />
            <Pager page={page} pageSize={PAGE_SIZE} total={records.data.total} onPage={setPage} />
          </>
        )}
      </Card>

      {open && <RecordDrawer recordId={open} onClose={() => setOpen(null)} onChanged={records.reload} />}
    </>
  );
}
