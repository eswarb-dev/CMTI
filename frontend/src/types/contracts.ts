/**
 * ManufacturaIQ frontend types.
 * QueryApi* types model the public FastAPI HTTP contract only.
 */

// Transport/UI lifecycle state owned by frontend
export type UiTransportState = 'idle' | 'uploading' | 'submitting' | 'success' | 'error';

// Business status returned by backend (never computed client-side)
export type BusinessStatus = 'needs_clarification' | 'pass' | 'human_review';

// Backend Health/Ready status
export type ConnectionStatus = 'online' | 'offline' | 'checking';

export interface HealthResponse {
  status: 'ok';
  service: 'manufacturaiq';
}

export interface ReadyResponse {
  status: 'ready';
  service: 'manufacturaiq';
  orchestrator: 'available';
}

export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  role: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}

export type RegisterRole =
  | 'Manufacturing Engineer'
  | 'Quality Engineer'
  | 'Maintenance Engineer'
  | 'Production Engineer'
  | 'Engineer'
  | 'Student / Researcher';

export interface RegisterRequest {
  username: string;
  display_name: string;
  role: RegisterRole;
  password: string;
}

export interface QueryDocumentContext {
  document_type?: string | null;
  manufacturer?: string | null;
  machine_family?: string | null;
  model?: string | null;
  document_id?: string | null;
  language?: string | null;
}

export interface QueryApiRequest {
  query: string;
  machine_id?: string | null;
  product_id?: string | null;
  batch_id?: string | null;
  time_start?: string | null;
  time_end?: string | null;
  document_context?: QueryDocumentContext | null;
}

export type ProviderStatus = 'SUCCESS' | 'FALLBACK' | 'UNAVAILABLE' | 'ERROR';
export type AgentName = 'DOCUMENT' | 'MAINTENANCE' | 'QUALITY' | 'PRODUCTION';
export type ReviewAction = 'PASS' | 'HUMAN_REVIEW';

export interface RoutingPayload {
  query_id: string;
  intent: string;
  selected_agents: AgentName[];
  needs_clarification: boolean;
  clarification_reason: string | null;
  risk_level: string;
  confidence: number | null;
  provider_status: ProviderStatus;
  decision_metadata: Record<string, unknown>;
}

export interface EvidenceProvenance {
  source_kind: string;
  source_dataset: string;
  source_id: string;
  source_file: string | null;
  document_id: string | null;
  record_id: string | null;
  raw_record_id: string | null;
  chunk_id: string | null;
  page_start: number | null;
  page_end: number | null;
  chapter: string | null;
  section: string | null;
  subsection: string | null;
}

export interface QueryEvidence {
  evidence_id: string;
  source_type: string;
  provenance: EvidenceProvenance;
  machine_id: string | null;
  product_id: string | null;
  batch_id: string | null;
  title: string;
  content: string;
  observed_at: string | null;
  retrieval_score: number | null;
  decision_score: number | null;
  metadata: Record<string, unknown>;
}

export interface EvidenceConflict {
  conflict_id: string;
  evidence_ids: string[];
  conflict_type: string;
  description: string;
  severity: string;
  resolved: boolean;
  resolution_note: string | null;
}

export interface EvidenceBundlePayload {
  query_id: string;
  evidence: QueryEvidence[];
  conflicts: EvidenceConflict[];
  missing_information: string[];
  warnings: string[];
  metadata: Record<string, unknown>;
}

export interface ReasoningCitation {
  evidence_id: string;
  label: string | null;
}

export interface ReasoningPayload {
  query_id: string;
  observations: string[];
  possible_causes: string[];
  recommended_checks: string[];
  missing_information: string[];
  citations: ReasoningCitation[];
  raw_answer: string;
  provider_status: ProviderStatus;
  model: string | null;
  metadata: Record<string, unknown>;
}

export interface ReviewPayload {
  query_id: string;
  action: ReviewAction;
  reasons: string[];
  confidence: number | null;
  provider_status: ProviderStatus;
  metadata: Record<string, unknown>;
}

export interface QueryApiResponse {
  query_id: string;
  status: BusinessStatus;
  routing: RoutingPayload;
  evidence: EvidenceBundlePayload | null;
  reasoning: ReasoningPayload | null;
  review: ReviewPayload | null;
}

export interface ApiValidationError {
  detail?: unknown;
}

export interface EvidenceCitation {
  citation_number: number;
  evidence_id: string;
  label: string;
  document_title: string;
  document_id?: string | null;
  page_number?: number;
  snippet: string;
  section?: string;
  retrieval_score?: number | null;
  source_label?: 'Uploaded document' | 'Built-in document' | 'Structured evidence';
}

export interface ReasoningSections {
  observations?: string[];
  possible_causes?: string[];
  recommended_checks?: string[];
  missing_information?: string[];
}

/**
 * Temporary session-attached PDF metadata
 */
export interface SessionAttachment {
  file: File;
  name: string;
  size: number;
  uploadedAt: Date;
}

/**
 * Chat Message Model for UI rendering
 */
export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  status?: BusinessStatus;
  citations?: EvidenceCitation[];
  reasoning?: ReasoningSections;
  evidenceBundle?: QueryEvidence[];
  reviewReasons?: string[];
  attachmentName?: string;
}

/**
 * Conversation representation in Sidebar
 */
export interface ConversationSummary {
  id: string;
  title: string;
  dateGroup: 'Today' | 'Yesterday' | 'Older';
  timestamp: string;
  lastMessageSnippet?: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

/**
 * Document in Knowledge Base / PDF Library
 */
export interface IndexedDocument {
  id: string;
  title: string;
  filename: string;
  sizeBytes: number;
  sizeFormatted: string;
  dateAdded: string;
  pageCount: number;
  manufacturer?: string;
  documentType?: string;
  isIndexed: boolean;
}

/**
 * Dynamic user documents served by GET /api/documents (STEP 19B2).
 * Mirrors the backend DocumentResponse schema; internal ingestion
 * fields (storage paths, SHA-256, registry paths) are never exposed.
 */
export type DocumentRecordStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED';

export interface UserDocument {
  document_id: string;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  status: DocumentRecordStatus;
  page_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  error_code: string | null;
  error_message: string | null;
}

export interface DocumentListResponse {
  documents: UserDocument[];
  count: number;
}

export interface DocumentUploadResponse extends UserDocument {
  duplicate: boolean;
}

export interface DocumentDeleteResponse {
  document_id: string;
  deleted: boolean;
}
