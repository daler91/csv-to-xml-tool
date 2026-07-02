export interface FieldDescription {
  description: string;
  conditional_rule?: string;
}

export interface DataQualityCheck {
  key: string;
  label: string;
  count: number;
  severity: "error" | "warning";
  /** Plain-language consequence, e.g. "these rows will be skipped". */
  detail: string;
  column: string | null;
}

export interface DataQualityReport {
  total_rows: number;
  /** Only checks with count > 0 are included; may be empty. */
  checks: DataQualityCheck[];
}

export interface PreviewResponse {
  headers: string[];
  rows: Record<string, string>[];
  total_rows: number;
  column_status: {
    matched: string[];
    missing: string[];
    extra: string[];
    suggestions: Array<{
      csv_column: string;
      suggested_match: string;
      score: number;
    }>;
    field_requirements: Record<string, "required" | "optional" | "conditional">;
    field_descriptions?: Record<string, FieldDescription>;
  };
  /** Absent when talking to an older worker without the data-quality report. */
  data_quality?: DataQualityReport;
}

export interface MappingTemplate {
  id: string;
  name: string;
  converterType: string;
  mapping: Record<string, string>;
  updatedAt: string;
}

export interface ConvertRequest {
  job_id: string;
  csv_content: string;
  converter_type: string;
  column_mapping?: Record<string, string>;
}

/**
 * Structured XSD validation error (worker Contract B). Every trackable
 * field is nullable — the worker sets what it can map back from the raw
 * validator message; `message` and `friendly_message` are always present.
 */
export interface XsdErrorDetail {
  line: number | null;
  row_number: number | null;
  record_id: string | null;
  element: string | null;
  field_label: string | null;
  csv_column: string | null;
  message: string;
  friendly_message: string;
}

export interface ConvertResponse {
  xml_content: string;
  stats: {
    total: number;
    successful: number;
    errors: number;
    warnings: number;
  };
  xsd_valid: boolean;
  xsd_errors: string[];
  /** Absent when talking to an older worker without structured details. */
  xsd_error_details?: XsdErrorDetail[];
  issues: ValidationIssue[];
  cleaning_diff: CleaningDiffEntry[];
}

export interface ValidationIssue {
  record_id: string;
  severity: "error" | "warning";
  category: string;
  field_name: string;
  message: string;
}

export interface CleaningDiffEntry {
  row: number;
  record_id: string;
  field: string;
  original: string;
  cleaned: string;
  cleaning_type: string;
}

export interface ProgressEvent {
  processed: number;
  total: number;
  errors: number;
  warnings: number;
  status: string;
}
