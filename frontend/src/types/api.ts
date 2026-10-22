export type RiskLevel = "Critical" | "High" | "Medium" | "Low" | "Needs review" | "None";
export type ReviewStatus = "new" | "investigating" | "reviewed";
export type ScanStatus = "uploaded" | "queued" | "running" | "completed" | "failed";

export interface Health {
  status: "ok" | "degraded";
  backend_reachable: boolean;
  model_loaded: boolean;
  model_version: string | null;
  model_error: string | null;
  database_ok: boolean;
  database_error: string | null;
  ready: boolean;
  model_is_synthetic: boolean;
  checked_at: string;
}

export interface Validation {
  rows: number;
  columns_total: number;
  features_expected: number;
  features_detected: number;
  missing_required_features: string[];
  unexpected_columns: string[];
  metadata_columns: string[];
  context_columns_found: Record<string, string>;
  label_column_present: boolean;
  label_distribution: Record<string, number> | null;
  missing_values: number;
  invalid_values: number;
  rows_with_data_issues: number;
  duplicate_rows: number;
  compatible: boolean;
  errors: string[];
  warnings: string[];
  encoding: string;
}

export interface UploadResponse {
  scan_id: string | null;
  filename: string;
  size_bytes: number;
  validation: Validation;
}

export interface EvalMetrics {
  basis: string;
  n_samples: number;
  accuracy: number;
  macro_avg: { precision: number; recall: number; f1: number };
  weighted_avg: { precision: number; recall: number; f1: number };
  averaging_note: string;
  binary_detection: {
    true_positives: number;
    false_positives: number;
    true_negatives: number;
    false_negatives: number;
    precision: number | null;
    recall: number | null;
    f1: number | null;
    false_positive_rate: number | null;
    false_negative_rate: number | null;
  };
  labels: string[];
  confusion_matrix: number[][];
  per_class: { label: string; precision: number; recall: number; f1: number; support: number }[];
  caveat?: string;
}

export interface Scan {
  id: string;
  source: "upload" | "single" | "simulation" | "replay" | "live";
  filename: string | null;
  size_bytes: number | null;
  status: ScanStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  rows_total: number | null;
  rows_processed: number;
  error: string | null;
  model_version: string | null;
  records_stored: number;
  suspicious_records: number;
  records_requiring_review: number;
  validation?: Validation | null;
  summary: {
    records_analyzed: number;
    predicted_class_counts: Record<string, number>;
    risk_level_counts: Record<string, number>;
    duration_seconds?: number;
    feature_vectors_stored?: number;
    feature_vector_cap?: number;
    label_comparison: EvalMetrics | null;
    realtime?: {
      mode: string;
      stop_reason: string | null;
      avg_throughput_flows_per_s: number;
      latency_ms: { p50: number; p95: number; max: number; mean: number; samples: number } | null;
      phases: RtPhase[];
      truth: RtTruth | null;
      latency_note: string;
    };
  } | null;
}

export interface RecordItem {
  id: string;
  scan_id: string;
  row_index: number;
  processed_at: string;
  event_time: string;
  event_time_source: "flow" | "processed";
  predicted_class: string;
  is_suspicious: boolean;
  attack_category: string | null;
  confidence: number | null;
  risk_level: RiskLevel;
  requires_review: boolean;
  risk_rule_id: string | null;
  risk_reason: string | null;
  risk_evidence: Record<string, number>;
  warnings: string[];
  ground_truth_label: string | null;
  src_ip: string | null;
  dst_ip: string | null;
  dst_port: number | null;
  review_status: ReviewStatus;
  review_note: string | null;
  reviewed_at: string | null;
  has_features?: boolean;
}

export interface RecordDetail extends RecordItem {
  features: Record<string, number | null> | null;
  influential_features: { feature: string; importance: number; value: number | null | undefined }[] | null;
  influential_features_note: string | null;
  features_note: string | null;
  confidence_note: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Overview {
  total_records: number;
  normal_records: number;
  suspicious_records: number;
  records_requiring_review: number;
  alerts_by_risk: Record<string, number>;
  records_by_risk: Record<string, number>;
  top_attack_categories: { category: string; count: number }[];
  alerts_by_review_status: Record<string, number>;
  scans_total: number;
  scans_completed: number;
  last_analysis_at: string | null;
  note: string;
}

export interface Traffic {
  classification: { normal: number; suspicious: number };
  categories: { category: string; count: number; suspicious: boolean }[];
  risk_levels: Record<string, number>;
  trend: { bucket: string; normal: number; suspicious: number }[];
  trend_bucket: "minute" | "hour" | "day";
  time_basis: "flow_timestamp" | "processing_time" | "mixed";
  time_basis_note: string;
  time_range: { from: string | null; to: string | null };
}

export interface FilterOptions {
  categories: string[];
  risk_levels: RiskLevel[];
  review_statuses: ReviewStatus[];
}

export interface ModelInfo {
  model_version: string;
  model_type: string;
  trained_at: string;
  training_seconds: number;
  random_seed: number;
  features: string[];
  features_count: number;
  classes: string[];
  preprocessing: string[];
  selection_criterion: string;
  supports_probability_estimates: boolean;
  confidence_note: string;
  feature_importances: { feature: string; importance: number }[] | null;
  dataset: {
    name: string;
    version: string | null;
    is_synthetic: boolean;
    rows_loaded: number;
    rows_used: number;
    duplicates_removed: number;
    max_rows_sampling: number | null;
    class_distribution: Record<string, number>;
    classes_dropped_too_few_samples: Record<string, number>;
  };
  split: { strategy: string; train_rows: number; validation_rows: number; test_rows: number; caveat: string };
  candidates: Record<
    string,
    {
      fit_seconds: number;
      validation: {
        accuracy: number;
        macro_precision: number;
        macro_recall: number;
        macro_f1: number;
        weighted_f1: number;
        attack_recall: number | null;
        false_positive_rate: number | null;
      };
    }
  >;
}

export interface Evaluation {
  model_version: string;
  selected_model: string;
  selected: EvalMetrics;
}

export interface SchemaInfo {
  format: string;
  required_features: string[];
  optional_columns: Record<string, string>;
  notes: string[];
  training_dataset: string | null;
  max_upload_mb: number;
}

export interface RiskRules {
  version: string;
  description: string;
  low_confidence_threshold: number;
  benign_review_confidence_below: number;
  max_imputed_fraction: number;
  confidence_cap_level: string;
  category_rules: Record<string, { level: string; rule_id: string; reason: string }>;
  default_rule: { level: string; rule_id: string; reason: string };
  escalations: {
    rule_id: string;
    description: string;
    categories: string[];
    min_confidence: number;
    conditions: { feature: string; op: string; value: number }[];
    raise_to: string;
  }[];
}

export interface Report {
  generated_at: string;
  scan: {
    id: string;
    filename: string | null;
    source: string;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
    rows_total: number | null;
    model_version: string | null;
    records_stored: number;
    suspicious_records: number;
    records_requiring_review: number;
  };
  dataset_summary: {
    records: number | null;
    features_detected: number | null;
    features_expected: number | null;
    missing_values: number | null;
    invalid_values: number | null;
    duplicate_rows: number | null;
    label_distribution: Record<string, number> | null;
    warnings: string[];
  };
  model: {
    version: string | null;
    type: string | null;
    trained_at: string | null;
    training_dataset: string | null;
    is_synthetic: boolean;
    held_out_test_macro_f1: number | null;
    evaluation_basis: string | null;
  };
  risk_rules_version: string;
  summary: Scan["summary"];
  classification: { normal: number; suspicious: number };
  categories: { category: string; count: number; suspicious: boolean }[];
  risk_levels: Record<string, number>;
  top_alerts: {
    id: string;
    row_index: number;
    event_time: string;
    predicted_class: string;
    confidence: number | null;
    risk_level: RiskLevel;
    requires_review: boolean;
    risk_rule_id: string | null;
    review_status: ReviewStatus;
  }[];
  disclaimer: string;
  counting_note: string;
}

export interface RecordQuery {
  scan_id?: string;
  classification?: "normal" | "suspicious" | "";
  category?: string;
  risk_level?: string;
  review_status?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: "asc" | "desc";
}

// ---------------------------------------------------------------- real-time
export type SessionState = "idle" | "running" | "finished" | "stopped" | "failed";

export interface RtPhaseSpec {
  label: string;
  start: number;
  duration: number;
  rate: number;
}

export interface RtScenario {
  name: string;
  seed?: number | null;
  duration_seconds: number;
  baseline_rate: number;
  phases: RtPhaseSpec[];
  description?: string;
}

export interface RtPhase {
  idx: number;
  label: string;
  start: number;
  duration: number;
  rate: number;
  status: "pending" | "active" | "done";
  flows?: number;
  flagged?: number;
  correct_category?: number;
  first_detection_s?: number | null;
  recall: number | null;
}

export interface RtAlert {
  id: string;
  time: string;
  predicted_class: string;
  confidence: number | null;
  risk_level: string;
  requires_review: boolean;
  is_suspicious: boolean;
  rule_id: string | null;
  truth_label: string | null;
  src_ip: string | null;
  dst_ip: string | null;
  latency_ms: number;
}

export interface RtTruth {
  tp: number;
  fp: number;
  tn: number;
  fn: number;
  flows_with_truth: number;
  precision: number | null;
  recall: number | null;
  false_positive_rate: number | null;
  f1: number | null;
}

export interface RtSnapshot {
  state: SessionState;
  session: {
    id: string;
    scan_id: string;
    mode: "simulation" | "replay" | "live";
    name: string;
    description: string | null;
    started_at: string;
    elapsed_s: number;
    duration_s: number | null;
    scenario: RtScenario | null;
    model_version: string;
    stop_reason: string | null;
    error: string | null;
  } | null;
  totals: { flows: number; suspicious: number; normal: number; needs_review: number; risk: Record<string, number> } | null;
  rate: number;
  latency_ms: { p50: number; p95: number; max: number; mean: number; samples: number } | null;
  processing_ms: { mean: number; max: number } | null;
  series: { t: number; normal: number; suspicious: number }[];
  truth: RtTruth | null;
  phases: RtPhase[];
  recent_alerts: RtAlert[];
  limits: { max_rate: number; max_seconds: number; max_records: number };
  simulator: { available: boolean; error: string | null };
  new_alerts?: RtAlert[];
  suppressed_alerts?: number;
}

export interface RtPreset {
  id: string;
  name: string;
  description: string;
  scenario: RtScenario;
}

export interface RtScenarios {
  available: boolean;
  error: string | null;
  classes: string[];
  pool_counts: Record<string, number>;
  presets: RtPreset[];
  limits: { max_rate: number; max_seconds: number; max_records: number };
  note: string;
  replayable_scans: { id: string; filename: string; rows: number | null; label_column_present: boolean }[];
}

export type RtStartBody =
  | { mode: "simulation"; scenario: RtScenario }
  | { mode: "replay"; replay: { scan_id: string; rate: number; loop: boolean }; max_duration_seconds?: number }
  | { mode: "live"; max_duration_seconds?: number };
