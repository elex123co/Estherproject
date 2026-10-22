import type { RecordItem } from "../types/api";
import { fmtEventTime, fmtPct, shortId } from "../utils/format";
import { ClassBadge, ReviewBadge, RiskBadge } from "./ui";

export function RecordsTable({ items, onOpen, showReview = true }: { items: RecordItem[]; onOpen: (id: string) => void; showReview?: boolean }) {
  return (
    <table className="data">
      <thead>
        <tr>
          <th>Record</th>
          <th>Event time</th>
          <th>Predicted class</th>
          <th>Policy</th>
          <th className="num" title="The model's own estimate. Not a calibrated probability.">Model confidence</th>
          <th>Risk level</th>
          {showReview && <th>Review</th>}
        </tr>
      </thead>
      <tbody>
        {items.map((r) => (
          <tr
            key={r.id}
            className="clickable"
            tabIndex={0}
            onClick={() => onOpen(r.id)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen(r.id))}
          >
            <td className="mono">{shortId(r.id)}</td>
            <td className="nowrap">{fmtEventTime(r.event_time, r.event_time_source)}</td>
            <td>{r.predicted_class}</td>
            <td><ClassBadge suspicious={r.is_suspicious} /></td>
            <td className="num">{r.confidence === null ? "n/a" : fmtPct(r.confidence)}</td>
            <td><RiskBadge level={r.risk_level} /></td>
            {showReview && <td><ReviewBadge status={r.review_status} /></td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
