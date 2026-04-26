export type Severity = "ok" | "info" | "warning" | "critical";
export type RiskRating = "Strong" | "Moderate" | "Weak" | "Unknown";
export type VendorReadiness = "Ready" | "Needs Review" | "Not Ready" | "Unknown";
export type Confidence = "high" | "medium" | "low";
// Per-field confidence — `none` means the rule explicitly couldn't find
// anything, distinct from a low-confidence guess.
export type FieldConfidenceLevel = "high" | "medium" | "low" | "none";

export interface FieldConfidence {
  value?: unknown;
  confidence: FieldConfidenceLevel;
  method?: string | null;
  evidence?: string | null;
  page_number?: number | null;
}

export interface CategoryScore {
  points: number;
  weight: number;
  ratio: number;
  reasons: string[];
}

export interface CUECDetail {
  text: string;
  page_number?: number | null;
  heading?: string | null;
}

export interface ValidationFinding {
  code: string;
  severity: Severity;
  title: string;
  detail: string;
  section?: string | null;
}

export interface ExtractedMetadata {
  company_name?: string | null;
  auditor_firm?: string | null;
  report_type?: string | null;
  opinion?: string | null;
  opinion_date?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  trust_service_criteria: string[];
  sections_present: string[];
  sections_missing: string[];
  subservice_organizations: string[];
  complementary_user_entity_controls: string[];
  exceptions_summary?: string | null;
}

export interface ReportDetail {
  id: string;
  filename: string;
  file_size_bytes: number;
  page_count: number;
  status: "processing" | "ready" | "failed";
  error_message?: string | null;
  company_name?: string | null;
  auditor_firm?: string | null;
  report_type?: string | null;
  opinion?: string | null;
  opinion_date?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  uploaded_at: string;
  updated_at: string;
  metadata: ExtractedMetadata;
  findings: ValidationFinding[];
  risk_score: number;
  risk_rating: RiskRating;
  report_age_days?: number | null;
  // Provenance side-channels — optional because legacy rows may not have
  // them. Always treat as possibly-undefined in components.
  field_confidence?: Record<string, FieldConfidence>;
  category_scores?: Record<string, CategoryScore>;
  cuec_details?: CUECDetail[];
}

export interface UploadResponse {
  id: string;
  filename: string;
  status: string;
  message: string;
  metadata: ExtractedMetadata;
  findings: ValidationFinding[];
}

export interface SuggestedQuestions {
  questions: string[];
}

export interface ChatCitation {
  chunk_id: string;
  page_number: number | null;
  snippet: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: ChatCitation[];
  created_at: string;
}

export interface ChatResponse {
  message: ChatMessage;
  citations: ChatCitation[];
  confidence: Confidence;
}

export interface ReportSummary {
  rating: RiskRating;
  executive_summary: string;
  key_strengths: string[];
  key_risks: string[];
  recommended_followups: string[];
  vendor_readiness: VendorReadiness;
  generated_at: string;
}
