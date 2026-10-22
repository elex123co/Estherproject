import { useState } from "react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useScope } from "../context/ScanContext";
import { RecordDrawer } from "../components/RecordDrawer";
import { RecordsTable } from "../components/RecordsTable";
import { Card, Empty, ErrorBox, Loading, Pager } from "../components/ui";
import { fmtInt } from "../utils/format";

const PAGE_SIZE = 20;
const STATUS_TABS = [
  { value: "", label: "All" },
  { value: "new", label: "New" },
  { value: "investigating", label: "Investigating" },
  { value: "reviewed", label: "Reviewed" },
];

export function AlertsPage() {
  const { scanId } = useScope();
  const [risk, setRisk] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("risk");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);

  const options = useAsync(() => api.filterOptions(scanId || undefined), [scanId]);
  const overview = useAsync(() => api.overview(scanId || undefined), [scanId]);
  const alerts = useAsync(
    () =>
      api.alerts({
        scan_id: scanId || undefined,
        risk_level: risk || undefined,
        category: category || undefined,
        review_status: status || undefined,
        sort,
        order: "desc",
        page,
        page_size: PAGE_SIZE,
      }),
    [scanId, risk, category, status, sort, page],
  );

  const r = overview.data?.alerts_by_review_status;
  const refresh = () => {
    alerts.reload();
    overview.reload();
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Alerts and threat review</h1>
          <p>
            Records the model flagged as suspicious, plus normal predictions that were too uncertain to trust. These are potential intrusions that
            require investigation, not confirmed incidents.
          </p>
        </div>
        {r && (
          <div className="row small muted">
            <span>New {fmtInt(r.new)}</span><span>Investigating {fmtInt(r.investigating)}</span><span>Reviewed {fmtInt(r.reviewed)}</span>
          </div>
        )}
      </div>

      <Card>
        <div className="filters">
          <div className="field">Review status
            <div className="seg" role="group" aria-label="Review status filter">
              {STATUS_TABS.map((t) => (
                <button key={t.value} className={status === t.value ? "on" : ""} onClick={() => { setStatus(t.value); setPage(1); }}>{t.label}</button>
              ))}
            </div>
          </div>
          <label className="field">Risk level
            <select value={risk} onChange={(e) => { setRisk(e.target.value); setPage(1); }}>
              <option value="">All</option>
              {options.data?.risk_levels.filter((l) => l !== "None").map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
          <label className="field">Predicted category
            <select value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }}>
              <option value="">All</option>
              {options.data?.categories.filter((c) => c !== "BENIGN").map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="field">Sort by
            <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
              <option value="risk">Risk (highest first)</option>
              <option value="confidence">Model confidence</option>
              <option value="event_time">Event time (newest first)</option>
            </select>
          </label>
        </div>
      </Card>

      <Card flush scroll>
        {alerts.loading && !alerts.data && <Loading />}
        {alerts.error && <div style={{ padding: 16 }}><ErrorBox error={alerts.error} onRetry={alerts.reload} /></div>}
        {alerts.data && alerts.data.total === 0 && (
          <Empty title="No alerts">
            {risk || category || status ? "No alerts match these filters." : "Nothing has been flagged yet. Analyze a dataset to populate the queue."}
          </Empty>
        )}
        {alerts.data && alerts.data.total > 0 && (
          <>
            <RecordsTable items={alerts.data.items} onOpen={setOpen} />
            <Pager page={page} pageSize={PAGE_SIZE} total={alerts.data.total} onPage={setPage} />
          </>
        )}
      </Card>

      {open && <RecordDrawer recordId={open} onClose={() => setOpen(null)} onChanged={refresh} />}
    </>
  );
}
