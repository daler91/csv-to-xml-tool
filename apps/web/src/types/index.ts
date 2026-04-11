export interface FieldDescription {
  description: string;
  conditional_rule?: string;
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
}

export interface ConvertRequest {
  job_id: string;
  csv_path: string;
  converter_type: string;
  column_mapping?: Record<string, string>;
}

export interface ConvertResponse {
  xml_path: string;
  xml_content?: string;
  stats: {
    total: number;
    successful: number;
    errors: number;
    warnings: number;
  };
  xsd_valid: boolean;
  xsd_errors: string[];
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
