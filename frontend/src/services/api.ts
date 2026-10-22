import type {
  Evaluation,
  FilterOptions,
  Health,
  ModelInfo,
  Overview,
  Page,
  RecordDetail,
  RecordItem,
  RecordQuery,
  Report,
  ReviewStatus,
  RiskRules,
  Scan,
  SchemaInfo,
  Traffic,
  RtScenarios,
  RtSnapshot,
  RtStartBody,
  UploadResponse,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;
  problems: string[];
  constructor(message: string, status: number, problems: string[] = []) {
    super(message);
    this.status = status;
    this.problems = problems;
  }
}

function describe(detail: unknown, fallback: string): { message: string; problems: string[] } {
  if (typeof detail === "string") return { message: detail, problems: [] };
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { message?: string; problems?: string[] };
    return { message: d.message ?? fallback, problems: d.problems ?? [] };
  }
  if (Array.isArray(detail)) {
    // FastAPI validation errors
    const msgs = detail.map((e) => (typeof e === "object" && e && "msg" in e ? String((e as { msg: unknown }).msg) : String(e)));
    return { message: "The request was not valid.", problems: msgs };
  }
  return { message: fallback, problems: [] };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError("Cannot reach the backend. Check that the API server is running.", 0);
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    const { message, problems } = describe(detail, `Request failed (${response.status}).`);
    throw new ApiError(message, response.status, problems);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  model: () => request<ModelInfo>("/api/model"),
  evaluation: () => request<Evaluation>("/api/model/evaluation"),
  schema: () => request<SchemaInfo>("/api/datasets/schema"),
  riskRules: () => request<RiskRules>("/api/risk/rules"),

  scans: (limit = 50) => request<{ items: Scan[] }>(`/api/scans${qs({ limit })}`),
  scan: (id: string) => request<Scan>(`/api/scans/${id}`),
  startAnalysis: (id: string) => request<Scan>(`/api/scans/${id}/analyze`, { method: "POST" }),
  deleteScan: (id: string) => request<void>(`/api/scans/${id}`, { method: "DELETE" }),
  predictRecord: (record: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/predict", json("POST", { record })),

  records: (q: RecordQuery) => request<Page<RecordItem>>(`/api/records${qs({ ...q })}`),
  alerts: (q: RecordQuery) => request<Page<RecordItem>>(`/api/alerts${qs({ ...q })}`),
  alert: (id: string) => request<RecordDetail>(`/api/alerts/${id}`),
  review: (id: string, body: { review_status?: ReviewStatus; review_note?: string }) =>
    request<RecordDetail>(`/api/alerts/${id}`, json("PATCH", body)),

  overview: (scanId?: string) => request<Overview>(`/api/stats/overview${qs({ scan_id: scanId })}`),
  traffic: (q: RecordQuery) => request<Traffic>(`/api/stats/traffic${qs({ ...q, page: undefined, page_size: undefined, sort: undefined, order: undefined })}`),
  filterOptions: (scanId?: string) => request<FilterOptions>(`/api/stats/filter-options${qs({ scan_id: scanId })}`),

  report: (id: string) => request<Report>(`/api/scans/${id}/report`),
  exportUrl: (id: string, scope: "alerts" | "all", includeContext = false) =>
    `${BASE}/api/scans/${id}/export.csv${qs({ scope, include_network_context: includeContext || undefined })}`,

  rtScenarios: () => request<RtScenarios>("/api/realtime/scenarios"),
  rtStatus: () => request<RtSnapshot>("/api/realtime/status"),
  rtStart: (body: RtStartBody) => request<RtSnapshot>("/api/realtime/sessions", json("POST", body)),
  rtStop: () => request<RtSnapshot>("/api/realtime/sessions/stop", { method: "POST" }),
  rtStreamUrl: () => `${BASE}/api/realtime/stream`,

  /** Upload with progress (fetch cannot report upload progress). */
  upload(file: File, onProgress: (fraction: number) => void): Promise<UploadResponse> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/api/datasets/upload`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
      xhr.onerror = () => reject(new ApiError("Cannot reach the backend. Check that the API server is running.", 0));
      xhr.onload = () => {
        let body: unknown = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body as UploadResponse);
        } else {
          const { message, problems } = describe((body as { detail?: unknown } | null)?.detail, `Upload failed (${xhr.status}).`);
          reject(new ApiError(message, xhr.status, problems));
        }
      };
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },
};
