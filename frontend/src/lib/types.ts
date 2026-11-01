/**
 * API types, mirroring the backend serializers.
 *
 * Hand-written rather than generated from the OpenAPI schema. Many of this API's
 * responses are rich nested documents (a knowledge base, an architecture graph, a metrics
 * dashboard) which the generator types as `object` — so generated types would be weaker
 * than these, not stronger. Where a shape is load-bearing for a safety decision (trust
 * state, gate status, confidence scores) it is typed precisely and commented.
 */

// =====================================================================================
// Shared
// =====================================================================================

export interface Paginated<T> {
  count: number;
  page: number;
  page_size: number;
  num_pages: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

export interface SourceRef {
  id: string;
  title: string;
  url: string;
  fetched_at: string;
}

/**
 * How a product claim may be presented. Mirrors the backend's status vocabulary — the UI
 * must render each differently, and `vendor_claim` must always be attributed to IOMETE
 * rather than stated as a COMPASS finding.
 */
export type ClaimStatus =
  | "verified"
  | "vendor_claim"
  | "needs_confirmation"
  | "industry_concept";

// =====================================================================================
// Identity
// =====================================================================================

export type SystemRole = "customer" | "fde" | "fde_lead" | "platform_admin";
export type MembershipRole = "viewer" | "engineer" | "admin";

export interface MembershipBrief {
  id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: MembershipRole;
  is_default: boolean;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  job_title: string;
  system_role: SystemRole;
  is_iomete_staff: boolean;
  avatar_initials: string;
  timezone_name: string;
  is_active: boolean;
  last_seen_at: string | null;
  memberships: MembershipBrief[];
  is_synthetic: boolean;
  created_at: string;
}

export interface TokenPair {
  access: string;
  refresh: string;
  user: User;
}

export interface DemoAccount {
  email: string;
  password: string;
  full_name: string;
  system_role: SystemRole;
  organization: string | null;
  description: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  industry: string;
  region: string;
  employee_band: string;
  deployment_model: string;
  cloud_provider: string;
  iomete_version: string;
  environment_label: string;
  kubernetes_distribution: string;
  object_storage: string;
  support_tier?: string;
  assigned_fde?: string | null;
  assigned_fde_name?: string | null;
  data_residency_requirement: string;
  notes?: string;
  is_active: boolean;
  is_synthetic: boolean;
  member_count: number;
  open_ticket_count: number;
  created_at: string;
  updated_at: string;
}

export interface Membership {
  id: string;
  user: string;
  user_email: string;
  user_full_name: string;
  organization: string;
  organization_name: string;
  role: MembershipRole;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  actor: string | null;
  actor_label: string;
  organization: string | null;
  organization_name: string | null;
  target_type: string;
  target_id: string;
  summary: string;
  metadata: Record<string, unknown>;
  request_id: string;
  ip_address: string | null;
  created_at: string;
}

// =====================================================================================
// System status — what is real in this deployment
// =====================================================================================

export interface SystemStatus {
  demo_mode: boolean;
  demo_mode_notice: string;
  ai: {
    llm_provider: string;
    llm_provider_requested: string;
    llm_model: string;
    llm_live: boolean;
    embedding_provider: string;
    embedding_provider_requested: string;
    embedding_dim: number;
    embedding_live: boolean;
    notice: string;
  };
  retrieval: {
    strategy: string;
    channels: string[];
    weights: Record<string, number>;
    fusion: string;
    vector_backend: "pgvector" | "numpy";
    vector_backend_reason: string;
    embedding: {
      provider: string;
      model: string;
      dim: number;
      is_live: boolean;
      requested: string;
    };
  };
  integrations: Record<string, IntegrationModeReport | string>;
  knowledge_base: {
    available: boolean;
    last_verified?: string;
    schema_version?: string;
    source_count?: number;
    capability_count?: number;
    verified_capability_count?: number;
    needs_confirmation_count?: number;
    do_not_claim_count?: number;
    error?: string;
  };
}

export interface IntegrationModeReport {
  provider: string;
  mode: "demo" | "configured" | "connected";
  is_simulated: boolean;
  summary: string;
  capabilities: string[];
  limitations: string[];
  missing_configuration: string[];
  last_tested_at: string | null;
  evidence: Record<string, unknown>;
  adapter?: string;
  purpose?: string;
}

// =====================================================================================
// Product knowledge
// =====================================================================================

export interface Sourced {
  status?: ClaimStatus;
  sources: SourceRef[];
}

export interface Capability extends Sourced {
  id: string;
  name: string;
  category: string;
  description: string;
  business_benefit: string;
  limitations: string | null;
}

export interface Technology extends Sourced {
  id: string;
  name: string;
  role: string;
  plain_english: string;
  iomete_usage: string;
  official_quote?: string;
  documented_properties?: string[];
}

export interface Concept extends Sourced {
  id: string;
  title: string;
  plain_english: string;
  analogy?: string;
  strength?: string;
  weakness?: string;
  iomete_note?: string;
  official_claims?: string[];
  why_it_matters?: string;
}

export interface ArchitectureService extends Sourced {
  id: string;
  name: string;
  tier: string;
  what_it_does: string;
  why_needed: string;
  customer_gain: string;
  note?: string;
}

export interface ArchitectureReference {
  summary: string;
  status: ClaimStatus;
  sources: SourceRef[];
  tiers: { id: string; name: string; description: string; components: string[] }[];
  services: ArchitectureService[];
}

export interface PersonaSummary {
  id: string;
  label: string;
  short: string;
}

export interface PersonaKeyPoint extends Sourced {
  title: string;
  body: string;
  caveat?: boolean;
}

export interface Persona extends PersonaSummary {
  opening: string;
  cares_about: string[];
  key_points: PersonaKeyPoint[];
  questions_to_ask_iomete: string[];
}

export interface ExplainerQuestion extends Sourced {
  id: string;
  question: string;
  answer: string;
  concept_refs: string[];
}

export interface Integration extends Sourced {
  name: string;
  category: string;
}

export interface StorageBackend extends Sourced {
  name: string;
  scheme: string | null;
  config_type: string | null;
  note?: string;
}

export interface DeploymentModel extends Sourced {
  id: string;
  name: string;
  description: string;
  best_for: string;
}

export interface ProductKnowledge {
  meta: { schema_version: string; last_verified: string; disclaimer: string };
  sources: SourceRef[];
  positioning: Sourced & {
    tagline: string;
    secondary_tagline: string;
    one_liner: string;
    official_description: string;
  };
  concepts: Concept[];
  technologies: Technology[];
  capabilities: Capability[];
  architecture: ArchitectureReference;
  storage_backends: StorageBackend[];
  integrations: Integration[];
  deployment_models: DeploymentModel[];
  explainer_questions: ExplainerQuestion[];
  personas: Persona[];
  do_not_claim: string[];
  status_legend: Record<ClaimStatus, string>;
}

export interface ExplainerPayload {
  positioning: ProductKnowledge["positioning"];
  concepts: Concept[];
  questions: ExplainerQuestion[];
  technologies: Technology[];
  personas: PersonaSummary[];
  status_legend: Record<ClaimStatus, string>;
}

export interface ArchitecturePayload {
  architecture: ArchitectureReference;
  technologies: Technology[];
  storage_backends: StorageBackend[];
  integrations: Integration[];
  deployment_models: DeploymentModel[];
  status_legend: Record<ClaimStatus, string>;
}

// =====================================================================================
// Architecture graph (React Flow)
// =====================================================================================

/**
 * Whether a graph node is a documented IOMETE component or COMPASS's own conceptual
 * placement. The renderer must visually distinguish these — a dashed proposal must never
 * look like a solid documented fact.
 */
export type NodeClaimStatus =
  | "documented"
  | "documented_integration"
  | "customer_system"
  | "conceptual"
  | "needs_confirmation";

export interface GraphNode {
  id: string;
  label: string;
  layer: string;
  kind: string;
  claim_status: NodeClaimStatus;
  description: string;
  sources: SourceRef[];
  detail: {
    why_needed?: string;
    customer_gain?: string;
    note?: string;
    uri_scheme?: string;
  };
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  kind: string;
  claim_status: NodeClaimStatus;
}

export interface GraphLayer {
  id: string;
  label: string;
  order: number;
  description: string;
}

export interface GraphLegendEntry {
  claim_status: NodeClaimStatus;
  label: string;
  meaning: string;
  render: string;
}

export interface IntegrationNote {
  system: string;
  mechanism: string;
  claim_status: NodeClaimStatus;
  note: string;
  sources: SourceRef[];
}

export interface ArchitectureGraph {
  title: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  layers: GraphLayer[];
  legend: GraphLegendEntry[];
  narrative: string;
  integration_notes: IntegrationNote[];
  open_questions: string[];
  conceptual_disclaimer: string;
  cited_sources: string[];
  is_illustrative?: boolean;
}

export interface ArchitectureRecommendation extends Omit<ArchitectureGraph, "legend"> {
  id: string;
  prospect: string | null;
  assessment: string | null;
  inputs: Record<string, unknown>;
  cited_source_detail: SourceRef[];
  legend?: GraphLegendEntry[];
  is_synthetic: boolean;
  created_at: string;
}

// =====================================================================================
// Fit assessment
// =====================================================================================

export type FitBand =
  | "strong"
  | "promising"
  | "conditional"
  | "limited"
  | "needs_discussion";

export interface RubricEntry {
  dimension: string;
  label: string;
  weight: number;
  awarded: number;
  max: number;
  reasoning: string;
  improves_with: string;
}

export interface FitRequirement {
  requirement: string;
  detail: string;
  sources: string[];
  status: ClaimStatus;
}

export interface FitAdvantage {
  advantage: string;
  detail: string;
  sources: string[];
  status: ClaimStatus;
}

export interface FitGap {
  gap: string;
  detail: string;
  mitigation: string;
  severity: "high" | "medium" | "low";
}

export interface FitAssessment {
  id: string;
  prospect: string;
  rubric_version: string;
  /** Indicative only. Always render alongside `rubric` and `score_caveat`. */
  indicative_score: number;
  band: FitBand;
  band_label: string;
  band_explanation: string;
  score_caveat: string;
  rubric: RubricEntry[];
  requirement_summary: string;
  suitability_reasons: string[];
  technical_requirements: FitRequirement[];
  advantages: FitAdvantage[];
  gaps: FitGap[];
  questions_for_sales: string[];
  /** Rubric hard caps that overrode the weighted band. Persisted, so a reopened
   * assessment shows the same reasoning as when it was generated. */
  caps_applied: string[];
  next_step: string;
  cited_sources: string[];
  cited_source_detail: SourceRef[];
  disclaimer: string;
  generated_by: string;
  is_synthetic: boolean;
  created_at: string;
}

export interface FitRubricDefinition {
  version: string;
  total_weight: number;
  dimensions: { key: string; label: string; weight: number; what_it_measures: string }[];
  bands: { band: FitBand; label: string; explanation: string }[];
  band_thresholds: Record<string, string>;
  hard_caps: string[];
  disclaimer: string;
  sources: SourceRef[];
}

export interface FitAssessmentResponse {
  assessment: FitAssessment;
  architecture: ArchitectureRecommendation;
  legend: GraphLegendEntry[];
  caps_applied: string[];
  rubric_definition_url: string;
}

export interface FitAnswers {
  company_type: string;
  company_name?: string;
  contact_role?: string;
  persona?: string;
  infrastructure_location: string;
  cloud_providers: string[];
  current_systems: string[];
  bi_tools: string[];
  data_volume: string;
  primary_use_case: string;
  secondary_use_cases: string[];
  sovereignty_requirement: string;
  challenges: string[];
  current_architecture: string;
  constraints: string[];
  kubernetes_maturity: string;
  team_size: string;
}

export interface DemoRequest {
  id: string;
  prospect: string;
  assessment: string | null;
  message: string;
  preferred_timeframe: string;
  interests: string[];
  status: string;
  status_label: string;
  is_synthetic: boolean;
  created_at: string;
  confirmation?: string;
  internal_notes?: string;
  assessment_band?: FitBand | null;
  assessment_score?: number | null;
  prospect_detail?: ProspectProfile;
}

export interface ProspectProfile {
  id: string;
  company_name: string;
  contact_name: string;
  contact_email: string;
  contact_role: string;
  persona: string;
  company_type: string;
  company_type_label: string;
  infrastructure_location: string;
  cloud_providers: string[];
  current_systems: string[];
  data_volume: string;
  primary_use_case: string;
  secondary_use_cases: string[];
  sovereignty_requirement: string;
  challenges: string[];
  current_architecture: string;
  constraints: string[];
  kubernetes_maturity: string;
  team_size: string;
  consent_given: boolean;
  consent_at: string | null;
  source: string;
  is_identified: boolean;
  is_synthetic: boolean;
  created_at: string;
}

// =====================================================================================
// Lakehouse playground
// =====================================================================================

export interface DatasetColumn {
  name: string;
  iceberg_type: string;
  sql_type: string;
  description: string;
}

export interface SimulatedIcebergMetadata {
  simulated: true;
  notice: string;
  format_version: number;
  current_snapshot_id: number;
  total_data_files: number;
  total_delete_files: number;
  total_records: number;
  estimated_size_bytes: number;
  manifest_files: number;
  snapshots: {
    snapshot_id: number;
    committed_at: string;
    operation: string;
    added_files: number;
    added_records: number;
    summary: string;
  }[];
  capabilities_demonstrated: string[];
}

export interface DatasetTable {
  name: string;
  description: string;
  columns: DatasetColumn[];
  row_count: number;
  partitioned_by: string[];
  simulated_metadata: SimulatedIcebergMetadata;
  ddl: string;
}

export interface PipelineStage {
  order: number;
  id: string;
  title: string;
  summary: string;
  iomete_component: string;
  sources: string[];
}

export interface DatasetPayload {
  dataset_id: string;
  label: string;
  description: string;
  is_synthetic: boolean;
  synthetic_notice: string;
  date_range: { from: string; to: string };
  total_rows: number;
  tables: DatasetTable[];
  pipeline: PipelineStage[];
  mode: "demo" | "connected";
  connected_catalog?: { namespaces: string[]; notice?: string; error?: string };
}

export interface ChartHint {
  type: "line" | "bar" | "grouped_bar" | "funnel";
  x: string;
  series?: string;
  y: string[];
}

export interface SampleQuery {
  id: string;
  title: string;
  teaches: string;
  difficulty: "starter" | "intermediate" | "advanced";
  chart: ChartHint;
  sql: string;
}

export interface ExecutionPlanStep {
  step: number;
  operator: string;
  detail: string;
  note: string;
  simulated: true;
  partition_pruning?: boolean;
}

export interface QueryResult {
  mode: "demo" | "connected";
  is_simulated: boolean;
  sql: string;
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  truncated: boolean;
  duration_ms: number;
  scanned_tables: string[];
  execution_plan: ExecutionPlanStep[];
  execution_plan_notice: string;
  simulation_notice: string;
  notice: string;
  sample: SampleQuery | null;
}

export interface PlaygroundStatus {
  mode: "demo" | "connected";
  mode_label: string;
  is_simulated: boolean;
  adapter: IntegrationModeReport;
  sql_execution_available: boolean;
  sql_execution_note: string;
  limits: {
    max_rows: number;
    max_columns: number;
    statement_timeout_seconds: number;
    read_only: boolean;
  };
}

// =====================================================================================
// Tickets
// =====================================================================================

export type TicketStatus =
  | "new"
  | "triaging"
  | "awaiting_customer"
  | "in_progress"
  | "escalated"
  | "resolved"
  | "closed";

export type Severity = "critical" | "high" | "medium" | "low";

export type GateStatus = "clean" | "penalised" | "gated";

export interface TicketListItem {
  id: string;
  reference: string;
  title: string;
  component: string;
  component_label: string;
  category: string;
  category_label: string;
  severity: Severity;
  severity_label: string;
  status: TicketStatus;
  status_label: string;
  iomete_version: string;
  environment: string;
  organization: string;
  organization_name: string;
  symptom_labels: string[];
  resolution_verified: boolean;
  self_service_resolved: boolean;
  is_synthetic: boolean;
  age_hours: number;
  has_approved_playbook: boolean;
  created_at: string;
  resolved_at: string | null;
}

export interface TicketEvent {
  id: string;
  event_type: string;
  event_type_label: string;
  author: string | null;
  author_name: string | null;
  author_label: string;
  body: string;
  is_internal: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface TicketAttachment {
  id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  redaction_applied: boolean;
  redaction_summary: Record<string, number>;
  is_internal: boolean;
  created_at: string;
  download_url: string;
}

export interface NormalizedSummary {
  error_codes: string[];
  symptoms: { key: string; label: string }[];
  key_phrases: string[];
  affected_components: Record<string, number>;
  extracted_version: string;
  confidence_note: string;
}

export interface Ticket extends Omit<TicketListItem, "organization"> {
  organization: Pick<
    Organization,
    "id" | "name" | "slug" | "deployment_model" | "cloud_provider" | "iomete_version"
  >;
  description: string;
  error_message: string;
  diagnostics: string;
  redaction_summary: Record<string, number>;
  redaction_notice: string;
  deployment_model: string;
  cloud_provider: string;
  kubernetes_distribution: string;
  normalized_summary: NormalizedSummary;
  escalation_reason: string;
  escalated_at: string | null;
  resolution_summary: string;
  resolution_evidence: string;
  resolution_verified_at: string | null;
  time_to_resolution_seconds: number | null;
  events: TicketEvent[];
  attachments: TicketAttachment[];
  updated_at: string;
  /** FDE-only fields. Absent for a customer role — never assume they are present. */
  assigned_fde?: string | null;
  assigned_fde_name?: string | null;
  reporter?: string | null;
  reporter_name?: string | null;
  reporter_label?: string;
  fde_investigation_minutes?: number | null;
  resolution_quality?: number | null;
  cluster?: string | null;
  cluster_title?: string | null;
  first_response_at?: string | null;
  external_provider?: string;
  external_reference?: string;
  external_url?: string;
  fingerprint_detail?: {
    id: string;
    digest: string;
    error_codes: string[];
    component: string;
    occurrence_count: number;
    distinct_organization_count: number;
  } | null;
}

export interface TicketIntakeReport {
  redaction_summary: Record<string, number>;
  redaction_notice: string;
  extracted_error_codes: string[];
  extracted_symptoms: string[];
  inferred_category: string;
  inferred_component: string;
  confidence_note: string;
  embedding_provider: string;
  fingerprint: string;
}

export interface CreatedTicket extends Ticket {
  intake: TicketIntakeReport;
}

export interface MatchEvidence {
  kind: string;
  label: string;
  detail: string;
  /** `negative` evidence must be rendered, not filtered out — it is the honest part. */
  strength: "strong" | "moderate" | "weak" | "negative";
}

export interface MatchedTicketBrief {
  id: string;
  reference: string;
  title: string;
  component: string;
  component_label: string;
  category: string;
  category_label: string;
  iomete_version: string;
  environment: string;
  deployment_model: string;
  resolution_summary: string;
  resolution_verified: boolean;
  resolution_verified_at: string | null;
  resolution_quality: number | null;
  symptom_labels: string[];
  is_synthetic: boolean;
  created_at: string;
  resolved_at: string | null;
}

/**
 * One proposed historical match.
 *
 * The three scores are *separate concepts* and must be rendered separately:
 * `similarity_score` says the reports look alike, `diagnosis_confidence` says the cause is
 * likely the same, `resolution_confidence` says the fix is likely to work here. Collapsing
 * them into one "match %" is the failure mode this product exists to avoid.
 */
export interface SimilarityMatch {
  id: string;
  rank: number;
  matched_ticket: MatchedTicketBrief;
  similarity_score: number;
  diagnosis_confidence: number;
  resolution_confidence: number;
  channel_scores: Record<string, number>;
  evidence: MatchEvidence[];
  matched_symptoms: string[];
  matched_symptom_labels: string[];
  gate_status: GateStatus;
  gate_status_label: string;
  gate_reason: string;
  retrieval_backend: string;
  score_explanations: {
    similarity_score: string;
    diagnosis_confidence: string;
    resolution_confidence: string;
  };
  created_at: string;
}

export interface PlaybookMatch {
  id: string;
  rank: number;
  playbook: PlaybookListItem;
  similarity_score: number;
  resolution_confidence: number;
  gate_status: GateStatus;
  gate_status_label: string;
  gate_reason: string;
  evidence: MatchEvidence[];
  channel_scores: Record<string, number>;
  created_at: string;
}

export type Recommendation = "run_playbook" | "investigate" | "escalate";

export interface SimilarSearchResult {
  ticket: string;
  from_cache: boolean;
  matches: SimilarityMatch[];
  playbook_matches: PlaybookMatch[];
  recommendation?: Recommendation;
  recommendation_reason?: string;
  recommended_playbook_id?: string | null;
  explanation?: {
    summary?: string;
    diagnosis?: string;
    root_cause?: string;
    confidence_statement?: string;
    next_questions?: string[];
    recommended_resolution?: string;
    safety_notes?: string[];
    recommendation?: string;
    injection_noted?: string[];
  };
  diagnostic_questions?: string[];
  retrieval?: {
    vector_backend: string;
    channel_counts: Record<string, number>;
    channel_weights: Record<string, number>;
    candidate_count: number;
    gated_count: number;
    duration_ms: number;
    embedding_provider: string;
    notes: string[];
  };
  ai?: { provider: string; is_live_model: boolean; notice: string };
  note?: string;
}

export interface EscalationResult {
  ticket: Ticket;
  escalation_summary: {
    summary: string;
    what_was_ruled_out?: string[];
    what_was_observed?: string[];
    open_questions?: string[];
    suggested_next_action?: string;
    diagnostic_package: Record<string, unknown>;
  };
  ai: { provider: string; is_live_model: boolean; notice: string };
}

export interface IssueCluster {
  id: string;
  key: string;
  title: string;
  description: string;
  component: string;
  component_label: string;
  category: string;
  category_label: string;
  status: string;
  status_label: string;
  symptom_signature: string[];
  symptom_labels: string[];
  common_error_codes: string[];
  /** A working theory. Must never be rendered as a finding. */
  hypothesised_root_cause: string;
  /** Only an FDE investigation sets this. Gates how the UI may present the cluster. */
  is_root_cause_confirmed: boolean;
  confirmed_root_cause: string;
  investigation_notes: string;
  owner: string | null;
  owner_name: string | null;
  ticket_count: number;
  verified_resolution_count: number;
  affected_organization_count: number;
  playbook_count: number;
  caveat: string;
  is_synthetic: boolean;
  created_at: string;
  updated_at: string;
}

export interface FdeInbox {
  counts: Record<string, number>;
  buckets: Record<string, TicketListItem[]>;
  notes: Record<string, string>;
}

// =====================================================================================
// Playbooks and Resolution Replay
// =====================================================================================

export type ApprovalStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "rejected"
  | "deprecated";

export type RiskLevel = "informational" | "low" | "medium" | "high";

export type StepType =
  | "informational"
  | "read_only_diagnostic"
  | "configuration_review"
  | "change_requiring_approval"
  | "verification"
  | "escalation";

export type ResponseKind = "boolean" | "choice" | "text" | "numeric" | "acknowledge";

export interface PlaybookCommand {
  label: string;
  command: string;
  language: string;
  is_read_only: boolean;
}

export interface PlaybookStep {
  id: string;
  order: number;
  key: string;
  title: string;
  plain_explanation: string;
  what_to_inspect: string;
  expected_observation: string;
  why_this_step: string;
  step_type: StepType;
  step_type_label: string;
  risk_level: RiskLevel;
  risk_level_label: string;
  blast_radius: string;
  commands: PlaybookCommand[];
  commands_notice: string;
  response_kind: ResponseKind;
  response_options: { value: string; label: string; hint?: string }[];
  branches: Record<string, string>;
  is_terminal: boolean;
  requires_approval: boolean;
  is_read_only: boolean;
  references: { title: string; url: string }[];
  /** Present on the live step of an execution. */
  can_current_user_approve?: boolean;
}

export interface PlaybookListItem {
  id: string;
  playbook_id: string;
  version: number;
  title: string;
  description: string;
  component: string;
  component_label: string;
  category: string;
  category_label: string;
  risk_level: RiskLevel;
  risk_level_label: string;
  approval_status: ApprovalStatus;
  approval_status_label: string;
  /** The only flag that may style content as verified knowledge. */
  is_trusted: boolean;
  /** One sentence stating exactly what this playbook's status means. Always render it. */
  trust_notice: string;
  is_shared: boolean;
  applicable_versions: string;
  applicable_environments: string[];
  applicable_deployments: string[];
  symptoms: string[];
  symptom_labels: string[];
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  last_reviewed_at: string | null;
  review_due_at: string | null;
  is_review_overdue: boolean;
  usage_count: number;
  success_count: number;
  failure_count: number;
  /** `null` means untested, which is different from a zero success rate. */
  success_rate: number | null;
  step_count: number;
  generated_by: string;
  is_synthetic: boolean;
  created_at: string;
  updated_at: string;
}

export interface Playbook extends PlaybookListItem {
  confirmed_root_cause: string;
  preconditions: string[];
  expected_evidence: string[];
  resolution_instructions: string;
  verification_steps: string[];
  known_limitations: string;
  applicable_cloud_providers: string[];
  steps: PlaybookStep[];
  source_ticket: string | null;
  source_ticket_reference: string | null;
  cluster: string | null;
  cluster_title: string | null;
  supersedes: string | null;
  supersedes_version: number | null;
  rejection_reason: string;
  redaction_notes: string;
  origin_organization?: string | null;
  origin_organization_name?: string | null;
  created_by?: string | null;
  created_by_name?: string | null;
}

export interface GraphIssue {
  severity: "error" | "warning";
  step_key: string;
  message: string;
}

export type ExecutionStatus =
  | "in_progress"
  | "resolved"
  | "partially_resolved"
  | "not_resolved"
  | "escalated"
  | "abandoned";

export interface StepResponse {
  id: string;
  sequence: number;
  step: string;
  step_key: string;
  step_title: string;
  step_type: StepType;
  expected_observation: string;
  response_value: string;
  observation: string;
  matched_expectation: boolean | null;
  completed_by: string | null;
  completed_by_name: string | null;
  approval_granted_by: string | null;
  approval_granted_by_name: string | null;
  approval_granted_at: string | null;
  approval_note: string;
  next_step_key: string;
  created_at: string;
}

export interface Execution {
  id: string;
  ticket: string;
  ticket_reference: string;
  playbook: string;
  playbook_title: string;
  playbook_slug: string;
  playbook_version: number;
  status: ExecutionStatus;
  status_label: string;
  started_by: string | null;
  started_by_name: string | null;
  current_step: string | null;
  current_step_detail: PlaybookStep | null;
  path: string[];
  outcome_summary: string;
  outcome_evidence: string;
  diagnostic_summary: {
    warnings?: string[];
    observations?: {
      sequence: number;
      step_key: string;
      step_title: string;
      step_type: string;
      expected: string;
      response: string;
      observation: string;
      matched_expectation: boolean | null;
      at: string;
    }[];
  };
  steps_completed: number;
  /** An upper bound, not a target: a branching workflow can finish in fewer steps. */
  total_steps: number;
  responses: StepResponse[];
  completed_at: string | null;
  duration_seconds: number | null;
  created_at: string;
}

export interface AdvanceResult {
  execution: Execution;
  terminal: string | null;
  requires_outcome_capture: boolean;
  outcome_prompt: string;
}

export interface Applicability {
  applicable: boolean;
  reasons: string[];
  warnings: string[];
}

export interface EscalationPackage {
  playbook: {
    playbook_id: string;
    title: string;
    version: number;
    root_cause_tested: string;
  };
  path: string[];
  steps_completed: {
    sequence: number;
    title: string;
    step_type: string;
    what_to_inspect: string;
    expected: string;
    response_value: string;
    observation: string;
    matched_expectation: boolean | null;
  }[];
  confirmed_observations: string[];
  ruled_out: string[];
  outcome: string;
  outcome_summary: string;
  outcome_evidence: string;
  warnings: string[];
  duration_seconds: number | null;
}

export interface KnowledgeApproval {
  id: string;
  playbook: string;
  playbook_version: number;
  reviewer: string | null;
  reviewer_name: string | null;
  reviewer_label: string;
  decision: "approved" | "rejected" | "changes_requested" | "deprecated";
  decision_label: string;
  notes: string;
  redactions_made: string;
  applicability_changes: Record<string, unknown>;
  review_due_at: string | null;
  created_at: string;
}

export interface ExtractionResult {
  playbook: Playbook | null;
  duplicate_of: PlaybookListItem | null;
  redaction_flags: string[];
  notes: string[];
  ai: { provider: string; is_live_model: boolean; notice: string };
}

export interface KnowledgeReviewQueue {
  counts: {
    drafts: number;
    changes_requested: number;
    review_overdue: number;
    verified_tickets_without_a_playbook: number;
  };
  drafts: PlaybookListItem[];
  changes_requested: PlaybookListItem[];
  review_overdue: PlaybookListItem[];
  verified_tickets_without_a_playbook: TicketListItem[];
  notes: Record<string, string>;
}

// =====================================================================================
// Analytics
// =====================================================================================

/**
 * `estimated` means a stated model, not a measurement. `insufficient_data` means the
 * value is null because there were too few rows — render "not enough data", never "0".
 */
export type MetricConfidence =
  | "measured"
  | "estimated"
  | "insufficient_data"
  | "untested";

export interface Metric {
  key: string;
  label: string;
  value: number | Record<string, number | null> | null;
  unit: string;
  basis: string;
  confidence: MetricConfidence;
  sample_size: number;
  window: string;
  comparison: Record<string, unknown> | null;
  caveat: string;
}

export interface Methodology {
  principles: string[];
  confidence_levels: Record<string, string>;
  min_sample_size: number;
}

export interface Dashboard {
  window: string;
  window_label: string;
  generated_at: string;
  metrics: Metric[];
  methodology: Methodology;
}

export interface TrendPoint {
  bucket: string | null;
  created: number;
  self_service: number;
  escalated: number;
  verified: number;
}

export interface Trends {
  window: string;
  granularity: string;
  series: TrendPoint[];
  basis: string;
  sample_size: number;
}

export interface BreakdownRow {
  key: string;
  label: string;
  total: number;
  resolved: number;
  self_service: number;
  verified: number;
  self_service_rate: number | null;
  avg_resolution_hours: number | null;
}

export interface Breakdowns {
  window: string;
  sample_size: number;
  by_component: BreakdownRow[];
  by_category: BreakdownRow[];
  by_severity: BreakdownRow[];
  basis: string;
}

export interface PlaybookEffectivenessRow {
  playbook_id: string;
  version: number;
  title: string;
  component: string;
  component_label: string;
  risk_level: RiskLevel;
  usage_count: number;
  success_count: number;
  failure_count: number;
  success_rate: number | null;
  recorded_outcomes: number;
  confidence: MetricConfidence;
  is_review_overdue: boolean;
  approved_at: string | null;
}

export interface PlaybookEffectiveness {
  playbooks: PlaybookEffectivenessRow[];
  basis: string;
  sample_size: number;
}

export interface LifecycleStage {
  key: string;
  label: string;
  count: number;
  description: string;
}

export interface KnowledgeLifecycle {
  stages: LifecycleStage[];
  basis: string;
}

export interface FdeDashboard extends Dashboard {
  knowledge_lifecycle: KnowledgeLifecycle;
  playbook_effectiveness: PlaybookEffectiveness;
  trends: Trends;
}

// =====================================================================================
// Integrations
// =====================================================================================

export interface IntegrationConfiguration {
  id: string;
  provider: string;
  provider_label: string;
  display_name: string;
  organization: string | null;
  organization_name: string | null;
  config: Record<string, unknown>;
  /** Which credential keys exist. Values are never returned by the API. */
  credential_keys: string[];
  has_credentials: boolean;
  is_enabled: boolean;
  mode: "demo" | "configured" | "connected";
  mode_label: string;
  is_live: boolean;
  last_connection_test_at: string | null;
  last_connection_ok: boolean | null;
  last_connection_message: string;
  connection_detail: Record<string, unknown>;
  last_sync_at: string | null;
  last_sync_status: string;
  webhook_configured: boolean;
  adapter_description: IntegrationModeReport;
  created_at: string;
  updated_at: string;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  evidence: Record<string, unknown>;
  error_code: string;
  mode: string;
  integration: IntegrationConfiguration;
}

export interface SyncRun {
  id: string;
  integration: string;
  provider: string;
  direction: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  records_seen: number;
  records_created: number;
  records_updated: number;
  records_failed: number;
  attempt: number;
  error_code: string;
  error_message: string;
  /** True for a simulated run. Must be surfaced wherever the run appears. */
  was_simulated: boolean;
  detail: Record<string, unknown>;
}

export interface SyncResult {
  status: string;
  was_simulated: boolean;
  message: string;
  created: string[];
  updated: string[];
  failed: { key?: string; reason: string }[];
  run: SyncRun;
}

// =====================================================================================
// Call preparation
// =====================================================================================

/**
 * How a single statement in a call brief is substantiated.
 *
 * The first three mirror the product knowledge base. `assumed` and `unknown` exist only
 * in a brief, because a brief mixes sourced product facts with inferences about one
 * company — and the whole value of the feature is that it never blurs the two.
 */
export type BriefStatus = ClaimStatus | "assumed" | "unknown";

export interface BriefLine {
  text: string;
  status: BriefStatus;
  sources: string[];
  detail: string;
}

export interface BriefQuestion {
  question: string;
  answer: string;
  status: BriefStatus;
  sources: SourceRef[];
  source_ids?: string[];
  asked_by: string;
}

export interface BriefObjection {
  id: string;
  objection: string;
  position: string;
  status: BriefStatus;
  sources: SourceRef[];
  source_ids?: string[];
  if_pressed: string;
}

export interface BriefCapability {
  name: string;
  why_now: string;
  limitation: string;
  status: ClaimStatus;
  sources: SourceRef[];
  source_ids?: string[];
}

export interface BriefStackSignal {
  matched_on: string[];
  signal: string;
  implication: string;
  ask: string;
  status: BriefStatus;
}

export interface BriefCoverage {
  total_statements: number;
  sourced: number;
  unknown: number;
  assumed: number;
  /** Proportion of statements the documentation could not substantiate. */
  unknown_rate: number;
  note: string;
}

export interface CallBrief {
  company_name: string;
  industry: string;
  industry_label: string;
  meeting_type: string;
  headline: string;
  opening: string;
  inputs_given: { label: string; value: string }[];
  assumptions: BriefLine[];
  stack_signals: BriefStackSignal[];
  lead_with: BriefCapability[];
  likely_questions: BriefQuestion[];
  objections: BriefObjection[];
  qualifying_questions: string[];
  do_not_say: string[];
  unknowns: { question: string; why: string; asked_by: string }[];
  coverage: BriefCoverage;
  cited_sources: string[];
  disclaimer: string;
  brief_version: string;
}

export interface CallPrepOptions {
  industries: { value: string; label: string }[];
  meeting_types: { value: string; label: string }[];
  personas: { value: string; label: string }[];
  status_legend: Record<string, string>;
}

export interface CallPrepRequest {
  company_name: string;
  industry?: string;
  company_size?: string;
  meeting_type?: string;
  known_stack?: string[];
  attendee_personas?: string[];
}
