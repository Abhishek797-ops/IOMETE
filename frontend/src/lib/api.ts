/**
 * Typed API client.
 *
 * Design notes:
 *
 * * **One error type.** Every failure arrives as an `ApiError` carrying the backend's
 *   stable `code`, so components branch on a slug rather than parsing a message. The
 *   backend's error envelope is the contract; this is the only place that unwraps it.
 *
 * * **Tokens live in memory, with a refresh token in `sessionStorage`.** Not
 *   `localStorage`: a token that survives closing the tab is a token that survives a
 *   shared machine. Not a cookie either — the frontend is a separate origin, and
 *   cross-origin cookie CSRF adds risk without benefit here.
 *
 * * **One refresh in flight.** Six parallel requests hitting a 401 must trigger one
 *   refresh, not six. `refreshInFlight` holds the single promise they all await.
 */

import type {
  AdvanceResult,
  ApiErrorBody,
  Applicability,
  ArchitectureGraph,
  ArchitecturePayload,
  ArchitectureRecommendation,
  AuditEntry,
  Breakdowns,
  CallBrief,
  CallPrepOptions,
  CallPrepRequest,
  ConnectionTestResult,
  CreatedTicket,
  Dashboard,
  DatasetPayload,
  DemoAccount,
  DemoRequest,
  EscalationPackage,
  EscalationResult,
  Execution,
  ExplainerPayload,
  ExtractionResult,
  FdeDashboard,
  FdeInbox,
  FitAnswers,
  FitAssessment,
  FitAssessmentResponse,
  FitRubricDefinition,
  GraphIssue,
  GraphLegendEntry,
  IntegrationConfiguration,
  IssueCluster,
  KnowledgeApproval,
  KnowledgeLifecycle,
  KnowledgeReviewQueue,
  Membership,
  Methodology,
  Organization,
  Paginated,
  Persona,
  PersonaSummary,
  Playbook,
  PlaybookEffectiveness,
  PlaybookListItem,
  PlaygroundStatus,
  ProductKnowledge,
  ProspectProfile,
  QueryResult,
  SampleQuery,
  SimilarSearchResult,
  SyncResult,
  SyncRun,
  SystemStatus,
  Ticket,
  TicketEvent,
  TicketListItem,
  TokenPair,
  Trends,
  User,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

const API = `${API_BASE}/api/v1`;

const REFRESH_STORAGE_KEY = "compass.refresh";

// =====================================================================================
// Errors
// =====================================================================================

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field-level validation messages, for attaching to form inputs. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(this.details)) {
      if (key === "retry_after_seconds" || key === "incident_id") continue;
      if (Array.isArray(value) && typeof value[0] === "string") out[key] = value[0];
      else if (typeof value === "string") out[key] = value;
    }
    return out;
  }

  get isAuth(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** A step that needs approval the current user cannot give. */
  get needsApproval(): boolean {
    return this.code === "approval_required";
  }
}

/** A network failure, as opposed to an HTTP error response. */
export class NetworkError extends Error {
  constructor(cause?: unknown) {
    super(
      "Could not reach the COMPASS API. Check that the backend is running on " +
        `${API_BASE} and that your connection is available.`,
    );
    this.name = "NetworkError";
    this.cause = cause;
  }
}

// =====================================================================================
// Token store
// =====================================================================================

let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;
const authListeners = new Set<(user: User | null) => void>();

function readRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(REFRESH_STORAGE_KEY);
  } catch {
    // Private mode, or storage blocked. Sign-in still works for the session; it simply
    // will not survive a reload.
    return null;
  }
}

function writeRefreshToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.sessionStorage.setItem(REFRESH_STORAGE_KEY, token);
    else window.sessionStorage.removeItem(REFRESH_STORAGE_KEY);
  } catch {
    /* Non-fatal: see readRefreshToken. */
  }
}

export function setTokens(pair: { access: string; refresh: string }): void {
  accessToken = pair.access;
  writeRefreshToken(pair.refresh);
}

export function clearTokens(): void {
  accessToken = null;
  writeRefreshToken(null);
}

export function hasStoredSession(): boolean {
  return Boolean(accessToken ?? readRefreshToken());
}

export function onAuthChange(listener: (user: User | null) => void): () => void {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

function announceAuth(user: User | null): void {
  for (const listener of authListeners) listener(user);
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = readRefreshToken();
  if (!refresh) return null;

  // Collapse concurrent refreshes into one.
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API}/auth/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh }),
      });
      if (!response.ok) {
        clearTokens();
        announceAuth(null);
        return null;
      }
      const data = (await response.json()) as { access: string; refresh?: string };
      accessToken = data.access;
      // SimpleJWT rotates refresh tokens, so store the new one or the next refresh fails.
      if (data.refresh) writeRefreshToken(data.refresh);
      return data.access;
    } catch {
      clearTokens();
      announceAuth(null);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

// =====================================================================================
// Request core
// =====================================================================================

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Skip the Authorization header. Used for public endpoints and for login itself. */
  anonymous?: boolean;
  signal?: AbortSignal;
  /** Multipart upload: pass FormData as `body` and set this. */
  formData?: boolean;
  /** Next.js fetch cache hint for server-side calls. */
  revalidate?: number | false;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${API}${path.startsWith("/") ? path : `/${path}`}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function parseError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = response.statusText || "The request failed.";
  let details: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as ApiErrorBody | Record<string, unknown>;
    if (body && typeof body === "object" && "error" in body && body.error) {
      const envelope = (body as ApiErrorBody).error;
      code = envelope.code ?? code;
      message = envelope.message ?? message;
      details = envelope.details ?? {};
    } else if (body && typeof body === "object") {
      // DRF's own shape, for the few paths that bypass our handler (token refresh).
      details = body as Record<string, unknown>;
      const first = Object.values(details)[0];
      if (typeof first === "string") message = first;
      else if (Array.isArray(first) && typeof first[0] === "string") message = first[0];
    }
  } catch {
    /* Non-JSON error body; keep the status text. */
  }
  return new ApiError(response.status, code, message, details);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, anonymous, signal, formData, revalidate } = options;

  const send = async (token: string | null): Promise<Response> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (!formData && body !== undefined) headers["Content-Type"] = "application/json";
    if (token && !anonymous) headers.Authorization = `Bearer ${token}`;

    try {
      return await fetch(buildUrl(path, query), {
        method,
        headers,
        body:
          body === undefined ? undefined : formData ? (body as FormData) : JSON.stringify(body),
        signal,
        ...(revalidate === undefined
          ? {}
          : revalidate === false
            ? { cache: "no-store" as RequestCache }
            : { next: { revalidate } }),
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
      throw new NetworkError(cause);
    }
  };

  let response = await send(anonymous ? null : accessToken);

  // One retry after a refresh. Not for login/refresh themselves, which would loop.
  if (
    response.status === 401 &&
    !anonymous &&
    !path.startsWith("/auth/login") &&
    !path.startsWith("/auth/refresh")
  ) {
    const token = await refreshAccessToken();
    if (token) response = await send(token);
  }

  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;

  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

// =====================================================================================
// Endpoints
// =====================================================================================

export const api = {
  // --- System -----------------------------------------------------------------------
  systemStatus: () =>
    request<SystemStatus>("/system/status/", { anonymous: true, revalidate: 30 }),

  // --- Auth -------------------------------------------------------------------------
  async login(email: string, password: string): Promise<User> {
    const pair = await request<TokenPair>("/auth/login/", {
      method: "POST",
      body: { email, password },
      anonymous: true,
    });
    setTokens(pair);
    announceAuth(pair.user);
    return pair.user;
  },

  async logout(): Promise<void> {
    const refresh = readRefreshToken();
    if (refresh) {
      // A failure here is not worth blocking the user's sign-out; the local tokens are
      // cleared regardless, and the server-side token expires on its own.
      await request<void>("/auth/logout/", { method: "POST", body: { refresh } }).catch(
        () => undefined,
      );
    }
    clearTokens();
    announceAuth(null);
  },

  async restoreSession(): Promise<User | null> {
    if (!accessToken && !readRefreshToken()) return null;
    if (!accessToken) {
      const token = await refreshAccessToken();
      if (!token) return null;
    }
    try {
      const user = await request<User>("/auth/me/");
      announceAuth(user);
      return user;
    } catch {
      clearTokens();
      announceAuth(null);
      return null;
    }
  },

  me: () => request<User>("/auth/me/"),
  updateProfile: (body: Partial<Pick<User, "full_name" | "job_title" | "timezone_name">>) =>
    request<User>("/auth/me/", { method: "PATCH", body }),
  demoAccounts: () =>
    request<{ demo_mode: boolean; accounts: DemoAccount[] }>("/auth/demo-accounts/", {
      anonymous: true,
      revalidate: false,
    }),
  fdeDirectory: () => request<User[]>("/auth/fdes/"),

  // --- Users and organizations -------------------------------------------------------
  users: (query?: RequestOptions["query"]) =>
    request<Paginated<User>>("/auth/users/", { query }),
  createUser: (body: Record<string, unknown>) =>
    request<User>("/auth/users/", { method: "POST", body }),
  changeUserRole: (id: string, role: string) =>
    request<User>(`/auth/users/${id}/change-role/`, { method: "POST", body: { role } }),
  deactivateUser: (id: string) =>
    request<User>(`/auth/users/${id}/deactivate/`, { method: "POST", body: {} }),

  memberships: (query?: RequestOptions["query"]) =>
    request<Paginated<Membership>>("/auth/memberships/", { query }),
  createMembership: (body: { user: string; organization: string; role: string }) =>
    request<Membership>("/auth/memberships/", { method: "POST", body }),
  changeMembershipRole: (id: string, role: string) =>
    request<Membership>(`/auth/memberships/${id}/change-role/`, {
      method: "POST",
      body: { role },
    }),
  removeMembership: (id: string) =>
    request<void>(`/auth/memberships/${id}/`, { method: "DELETE" }),

  organizations: (query?: RequestOptions["query"]) =>
    request<Paginated<Organization>>("/organizations/", { query }),
  organization: (id: string) => request<Organization>(`/organizations/${id}/`),
  createOrganization: (body: Record<string, unknown>) =>
    request<Organization>("/organizations/", { method: "POST", body }),
  updateOrganization: (id: string, body: Record<string, unknown>) =>
    request<Organization>(`/organizations/${id}/`, { method: "PATCH", body }),
  organizationMembers: (id: string) =>
    request<Membership[]>(`/organizations/${id}/members/`),

  auditLog: (query?: RequestOptions["query"]) =>
    request<Paginated<AuditEntry>>("/auth/audit/", { query }),

  // --- Product knowledge (public) ----------------------------------------------------
  productKnowledge: () =>
    request<ProductKnowledge>("/knowledge/product/", { anonymous: true, revalidate: 300 }),
  explainer: () =>
    request<ExplainerPayload>("/knowledge/explainer/", { anonymous: true, revalidate: 300 }),
  personas: () =>
    request<PersonaSummary[]>("/knowledge/personas/", { anonymous: true, revalidate: 300 }),
  persona: (id: string) =>
    request<Persona>(`/knowledge/personas/${id}/`, { anonymous: true, revalidate: 300 }),
  architectureReference: () =>
    request<ArchitecturePayload>("/knowledge/architecture/", {
      anonymous: true,
      revalidate: 300,
    }),
  knowledgeSearch: (q: string, limit = 20) =>
    request<{ query: string; count: number; results: Record<string, unknown>[] }>(
      "/knowledge/search/",
      { anonymous: true, query: { q, limit } },
    ),
  doNotClaim: () =>
    request<{ do_not_claim: string[]; note: string }>("/knowledge/do-not-claim/", {
      anonymous: true,
      revalidate: 300,
    }),

  // --- Fit finder (public) -----------------------------------------------------------
  fitRubric: () =>
    request<FitRubricDefinition>("/fit-assessments/rubric/", {
      anonymous: true,
      revalidate: 300,
    }),
  createFitAssessment: (body: {
    answers: FitAnswers;
    contact_name?: string;
    contact_email?: string;
    consent_given?: boolean;
  }) =>
    request<FitAssessmentResponse>("/fit-assessments/", {
      method: "POST",
      body,
      anonymous: true,
    }),
  fitAssessment: (id: string) =>
    request<FitAssessment>(`/fit-assessments/${id}/`, { anonymous: true }),
  /** The architecture recommendation stored against an assessment, for a reopened link. */
  fitArchitecture: (id: string) =>
    request<ArchitectureRecommendation & { legend: GraphLegendEntry[] }>(
      `/fit-assessments/${id}/architecture/`,
      { anonymous: true },
    ),
  fitReport: (id: string) =>
    request<Record<string, unknown>>(`/fit-assessments/${id}/report/`, { anonymous: true }),
  fitAssessments: (query?: RequestOptions["query"]) =>
    request<Paginated<FitAssessment>>("/fit-assessments/", { query }),

  generateArchitecture: (answers: Partial<FitAnswers>) =>
    request<ArchitectureGraph>("/architecture/generate/", {
      method: "POST",
      body: { answers },
      anonymous: true,
    }),
  referenceArchitecture: () =>
    request<ArchitectureGraph>("/architecture/reference/", {
      anonymous: true,
      revalidate: 300,
    }),

  // --- Call preparation (public) -----------------------------------------------------
  callPrepOptions: () =>
    request<CallPrepOptions>("/call-prep/options/", { anonymous: true, revalidate: 300 }),
  callPrep: (body: CallPrepRequest) =>
    request<CallBrief>("/call-prep/", { method: "POST", body, anonymous: true }),

  createDemoRequest: (body: Record<string, unknown>) =>
    request<DemoRequest>("/demo-requests/", { method: "POST", body, anonymous: true }),
  demoRequests: (query?: RequestOptions["query"]) =>
    request<Paginated<DemoRequest>>("/demo-requests/", { query }),
  updateDemoRequest: (id: string, body: Record<string, unknown>) =>
    request<DemoRequest>(`/demo-requests/${id}/`, { method: "PATCH", body }),

  prospects: (query?: RequestOptions["query"]) =>
    request<Paginated<ProspectProfile>>("/prospects/", { query }),

  // --- Lakehouse playground (public) -------------------------------------------------
  playgroundStatus: () =>
    request<PlaygroundStatus>("/lakehouse-demo/status/", { anonymous: true, revalidate: 60 }),
  dataset: () =>
    request<DatasetPayload>("/lakehouse-demo/dataset/", { anonymous: true, revalidate: 300 }),
  sampleQueries: () =>
    request<{ dataset_id: string; queries: SampleQuery[] }>(
      "/lakehouse-demo/sample-queries/",
      { anonymous: true, revalidate: 300 },
    ),
  runQuery: (body: { sql?: string; sample_id?: string; session_key?: string }) =>
    request<QueryResult>("/lakehouse-demo/query/", { method: "POST", body, anonymous: true }),

  // --- Tickets -----------------------------------------------------------------------
  tickets: (query?: RequestOptions["query"]) =>
    request<Paginated<TicketListItem>>("/tickets/", { query }),
  ticket: (id: string) => request<Ticket>(`/tickets/${id}/`),
  createTicket: (body: Record<string, unknown>) =>
    request<CreatedTicket>("/tickets/", { method: "POST", body }),
  ticketEvents: (id: string) => request<TicketEvent[]>(`/tickets/${id}/events/`),
  addComment: (id: string, body: { body: string; is_internal?: boolean }) =>
    request<TicketEvent>(`/tickets/${id}/comment/`, { method: "POST", body }),
  changeTicketStatus: (id: string, status: string, note?: string) =>
    request<Ticket>(`/tickets/${id}/status/`, { method: "POST", body: { status, note } }),
  escalateTicket: (id: string, reason: string, executionId?: string) =>
    request<EscalationResult>(`/tickets/${id}/escalate/`, {
      method: "POST",
      body: { reason, ...(executionId ? { execution_id: executionId } : {}) },
    }),
  resolveTicket: (
    id: string,
    body: { summary: string; evidence: string; fde_investigation_minutes?: number },
  ) => request<Ticket>(`/tickets/${id}/resolve/`, { method: "POST", body }),
  verifyTicket: (id: string, body: { quality: number; note?: string }) =>
    request<Ticket>(`/tickets/${id}/verify/`, { method: "POST", body }),
  assignTicket: (id: string, assignedFde: string | null) =>
    request<Ticket>(`/tickets/${id}/assign/`, {
      method: "POST",
      body: { assigned_fde: assignedFde },
    }),
  uploadAttachment: (id: string, file: File, isInternal = false) => {
    const form = new FormData();
    form.append("file", file);
    form.append("is_internal", String(isInternal));
    return request<import("./types").TicketAttachment>(`/tickets/${id}/attachments/`, {
      method: "POST",
      body: form,
      formData: true,
    });
  },

  /** Returns the stored result set. Pass `refresh` to re-run retrieval. */
  similarTickets: (id: string, opts: { refresh?: boolean; limit?: number } = {}) =>
    opts.refresh
      ? request<SimilarSearchResult>(`/tickets/${id}/similar/`, {
          method: "POST",
          body: {},
          query: { limit: opts.limit },
        })
      : request<SimilarSearchResult>(`/tickets/${id}/similar/`, {
          query: { limit: opts.limit },
        }),

  // --- FDE ---------------------------------------------------------------------------
  fdeInbox: () => request<FdeInbox>("/fde/inbox/"),
  fdeDashboard: (window = "30d") =>
    request<FdeDashboard>("/fde/dashboard/", { query: { window } }),
  knowledgeReviewQueue: () => request<KnowledgeReviewQueue>("/fde/knowledge-review/"),

  clusters: (query?: RequestOptions["query"]) =>
    request<Paginated<IssueCluster>>("/fde/clusters/", { query }),
  cluster: (id: string) => request<IssueCluster>(`/fde/clusters/${id}/`),
  clusterTickets: (id: string) => request<TicketListItem[]>(`/fde/clusters/${id}/tickets/`),
  clusterHypothesis: (id: string) =>
    request<{
      hypothesis: string;
      is_confirmed: boolean;
      confidence_statement: string;
      suggested_investigation: string[];
      provider: string;
      provider_is_live: boolean;
      provider_notice: string;
    }>(`/fde/clusters/${id}/hypothesis/`, { method: "POST", body: {} }),
  confirmClusterRootCause: (id: string, body: { root_cause: string; notes?: string }) =>
    request<IssueCluster>(`/fde/clusters/${id}/confirm-root-cause/`, {
      method: "POST",
      body,
    }),
  updateClusterStatus: (id: string, body: { status: string; notes?: string }) =>
    request<IssueCluster>(`/fde/clusters/${id}/status/`, { method: "POST", body }),

  // --- Playbooks ---------------------------------------------------------------------
  playbooks: (query?: RequestOptions["query"]) =>
    request<Paginated<PlaybookListItem>>("/playbooks/", { query }),
  playbook: (id: string) => request<Playbook>(`/playbooks/${id}/`),
  updatePlaybook: (id: string, body: Record<string, unknown>) =>
    request<Playbook>(`/playbooks/${id}/`, { method: "PATCH", body }),
  replacePlaybookSteps: (id: string, steps: Record<string, unknown>[]) =>
    request<{ playbook: Playbook; graph_issues: GraphIssue[] }>(`/playbooks/${id}/steps/`, {
      method: "PUT",
      body: steps,
    }),
  validatePlaybook: (id: string) =>
    request<{ can_be_approved: boolean; issues: GraphIssue[] }>(
      `/playbooks/${id}/validate/`,
    ),
  playbookVersions: (id: string) =>
    request<PlaybookListItem[]>(`/playbooks/${id}/versions/`),
  playbookApprovals: (id: string) =>
    request<KnowledgeApproval[]>(`/playbooks/${id}/approvals/`),

  approvePlaybook: (id: string, body: Record<string, unknown>) =>
    request<{
      playbook: Playbook;
      approval: KnowledgeApproval;
      warnings: GraphIssue[];
    }>(`/playbooks/${id}/approve/`, { method: "POST", body }),
  rejectPlaybook: (id: string, reason: string) =>
    request<{ playbook: Playbook; approval: KnowledgeApproval }>(
      `/playbooks/${id}/reject/`,
      { method: "POST", body: { reason } },
    ),
  requestPlaybookChanges: (id: string, reason: string) =>
    request<{ playbook: Playbook; approval: KnowledgeApproval }>(
      `/playbooks/${id}/request-changes/`,
      { method: "POST", body: { reason } },
    ),
  deprecatePlaybook: (id: string, reason: string) =>
    request<{ playbook: Playbook; approval: KnowledgeApproval }>(
      `/playbooks/${id}/deprecate/`,
      { method: "POST", body: { reason } },
    ),
  newPlaybookVersion: (id: string) =>
    request<Playbook>(`/playbooks/${id}/new-version/`, { method: "POST", body: {} }),

  extractKnowledge: (ticketId: string, force = false) =>
    request<ExtractionResult>("/knowledge/extract/", {
      method: "POST",
      body: { ticket: ticketId, force },
    }),

  // --- Resolution Replay -------------------------------------------------------------
  executions: (query?: RequestOptions["query"]) =>
    request<Paginated<Execution>>("/playbook-executions/", { query }),
  execution: (id: string) => request<Execution>(`/playbook-executions/${id}/`),
  startExecution: (ticket: string, playbook: string) =>
    request<Execution>("/playbook-executions/", {
      method: "POST",
      body: { ticket, playbook },
    }),
  checkApplicability: (ticket: string, playbook: string) =>
    request<Applicability>("/playbook-executions/applicability/", {
      query: { ticket, playbook },
    }),
  advanceExecution: (
    id: string,
    body: { response_value: string; observation?: string; approval_note?: string },
  ) => request<AdvanceResult>(`/playbook-executions/${id}/advance/`, { method: "POST", body }),
  completeExecution: (
    id: string,
    body: { outcome: string; outcome_summary?: string; outcome_evidence?: string },
  ) => request<Execution>(`/playbook-executions/${id}/complete/`, { method: "POST", body }),
  escalationPackage: (id: string) =>
    request<EscalationPackage>(`/playbook-executions/${id}/escalation-package/`),

  // --- Analytics ---------------------------------------------------------------------
  dashboard: (window = "30d", organization?: string) =>
    request<Dashboard>("/analytics/dashboard/", { query: { window, organization } }),
  trends: (window = "90d", organization?: string) =>
    request<Trends>("/analytics/trends/", { query: { window, organization } }),
  breakdowns: (window = "90d", organization?: string) =>
    request<Breakdowns>("/analytics/breakdowns/", { query: { window, organization } }),
  playbookEffectiveness: () =>
    request<PlaybookEffectiveness>("/analytics/playbooks/"),
  knowledgeLifecycle: () => request<KnowledgeLifecycle>("/analytics/knowledge-lifecycle/"),
  methodology: () => request<Methodology>("/analytics/methodology/"),

  // --- Integrations ------------------------------------------------------------------
  integrations: (query?: RequestOptions["query"]) =>
    request<Paginated<IntegrationConfiguration>>("/integrations/", { query }),
  integration: (id: string) => request<IntegrationConfiguration>(`/integrations/${id}/`),
  createIntegration: (body: Record<string, unknown>) =>
    request<IntegrationConfiguration>("/integrations/", { method: "POST", body }),
  updateIntegration: (id: string, body: Record<string, unknown>) =>
    request<IntegrationConfiguration>(`/integrations/${id}/`, { method: "PATCH", body }),
  testIntegrationConnection: (id: string) =>
    request<ConnectionTestResult>(`/integrations/${id}/test-connection/`, {
      method: "POST",
      body: {},
    }),
  runIntegrationSync: (id: string, body: Record<string, unknown> = {}) =>
    request<SyncResult>(`/integrations/${id}/sync/`, { method: "POST", body }),
  integrationSyncRuns: (id: string) => request<SyncRun[]>(`/integrations/${id}/sync-runs/`),
  integrationStatus: () =>
    request<Record<string, unknown>>("/integrations/status/"),
};

export type Api = typeof api;
