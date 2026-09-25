"use client";

import { createAuthenticatedFetch } from "./authenticated-fetch";
import { createClient } from "./supabase/client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Demo mode lets the whole app be walked through with no Supabase project and
// no login, matching the backend's DEMO_AUTH. Off by default in production
// builds; set NEXT_PUBLIC_DEMO_MODE=true for a demo deployment.
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

const authenticatedFetch = createAuthenticatedFetch({
  baseUrl: API_BASE,
  getAccessToken: async () => {
    try {
      const { data } = await createClient().auth.getSession();
      return data.session?.access_token ?? null;
    } catch {
      // No Supabase configured — fine in demo mode, fatal otherwise (the
      // AuthenticationRequiredError below is what surfaces it).
      return null;
    }
  },
  getWorkspaceId: () =>
    typeof window === "undefined" ? null : localStorage.getItem("active_workspace_id"),
  allowAnonymous: () => DEMO_MODE,
});

export interface ApiResponse<T> {
  data?: T;
  error?: string;
}

export function normalizeApiError(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "An error occurred";
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return "An error occurred";
}

export interface DashboardSummary {
  total_leads: number;
  qualified_leads: number;
  closed_leads: number;
  unassigned_leads: number;
  average_intent_score: number;
  status_counts: Record<string, number>;
}

export interface SessionContext {
  user_id: string;
  workspace_id: string;
  role: "owner" | "admin" | "agent";
  broker_id: string | null;
}

export const authApi = {
  me: () => fetchApi<SessionContext>("/api/v1/auth/me"),
};

export interface WorkspaceMember {
  user_id: string;
  workspace_id: string;
  role: "owner" | "admin" | "agent";
  status: "invited" | "active" | "disabled";
  broker_id: string | null;
}

export const membersApi = {
  list: () => fetchApi<WorkspaceMember[]>("/api/v1/members/"),
  invite: (input: { email: string; role: WorkspaceMember["role"]; broker_id?: string }) =>
    fetchApi<WorkspaceMember>("/api/v1/members/invitations", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};

export const dashboardApi = {
  summary: () => fetchApi<DashboardSummary>("/api/v1/dashboard/summary"),
};

async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    const response = await authenticatedFetch(endpoint, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => null);
      return { error: normalizeApiError(error) };
    }

    const data = await response.json();
    return { data };
  } catch (error) {
    return { error: "Network error" };
  }
}

// Lead APIs
export interface ApiLead {
  id: string;
  source?: string;
  first_name?: string | null;
  last_name?: string | null;
  phone?: string | null;
  email?: string | null;
  preferred_language?: string;
  budget_min?: number | null;
  budget_max?: number | null;
  /** Set only when the lead stated it explicitly — never inferred. */
  budget_currency?: string | null;
  /** "total" | "year" | "month", when known. */
  budget_period?: string | null;
  property_type?: string | null;
  area_preference?: string[];
  timeline?: string | null;
  intent_score?: number;
  status?: string;
  assigned_broker?: string | null;
  created_at?: string;
  last_contact_at?: string | null;
}

export const leadsApi = {
  ingest: (leadData: LeadIngestInput) =>
    fetchApi<{ lead_id: string }>("/api/v1/leads/ingest", {
      method: "POST",
      body: JSON.stringify(leadData),
    }),

  list: (params?: { status?: string; limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.append("status", params.status);
    if (params?.limit) query.append("limit", params.limit.toString());
    if (params?.offset) query.append("offset", params.offset.toString());
    return fetchApi<ApiLead[]>(`/api/v1/leads/?${query.toString()}`);
  },

  getById: (id: string) => fetchApi<ApiLead>(`/api/v1/leads/${id}`),

  sendMessage: (id: string, message: { text: string; property_id?: string }) =>
    fetchApi<LeadMessageResponse>(`/api/v1/leads/${id}/message`, {
      method: "POST",
      body: JSON.stringify(message),
    }),

  assign: (id: string, brokerId: string) =>
    fetchApi(`/api/v1/leads/${id}/assign`, {
      method: "POST",
      body: JSON.stringify({ broker_id: brokerId }),
    }),
};

// Property APIs
export const propertiesApi = {
  search: (params?: {
    area?: string;
    property_type?: string;
    min_price?: number;
    max_price?: number;
    bedrooms?: number;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.area) query.append("area", params.area);
    if (params?.property_type) query.append("property_type", params.property_type);
    if (params?.min_price) query.append("min_price", params.min_price.toString());
    if (params?.max_price) query.append("max_price", params.max_price.toString());
    if (params?.bedrooms) query.append("bedrooms", params.bedrooms.toString());
    if (params?.limit) query.append("limit", params.limit.toString());
    return fetchApi(`/api/v1/properties/search?${query.toString()}`);
  },

  getById: (id: string) => fetchApi(`/api/v1/properties/${id}`),
};

// Workspace APIs (the /configure workflow builder)
export interface TeamMember {
  name: string;
  email?: string;
  phone?: string;
  role: "agent" | "broker" | "team_lead";
  languages: string[];
  specialization: string[];
  max_leads: number;
}

export interface DataSourceConfig {
  source: string;
  enabled: boolean;
  status: "not_configured" | "testing" | "connected" | "error";
  last_tested_at?: string | null;
  meta?: Record<string, unknown>;
}

export interface ChannelConfig {
  whatsapp_number?: string;
  whatsapp_connected: boolean;
  languages: string[];
  web_widget_enabled: boolean;
}

export interface Workspace {
  id: string;
  name: string;
  team: TeamMember[];
  data_sources: DataSourceConfig[];
  channels: ChannelConfig;
  status: "draft" | "live";
  created_at?: string;
  updated_at?: string;
}

export const workspaceApi = {
  create: (data: Partial<Workspace>) =>
    fetchApi<Workspace>("/api/v1/workspace/", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  get: (id: string) => fetchApi<Workspace>(`/api/v1/workspace/${id}`),

  list: () => fetchApi<Workspace[]>("/api/v1/workspace/"),

  update: (id: string, data: Partial<Workspace>) =>
    fetchApi<Workspace>(`/api/v1/workspace/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  launch: (id: string) =>
    fetchApi<Workspace>(`/api/v1/workspace/${id}/launch`, { method: "POST" }),

  testDataSource: (source: string) =>
    fetchApi<{ source: string; ok: boolean; message: string; sample_count: number }>(
      `/api/v1/workspace/data-sources/${source}/test`,
      { method: "POST" }
    ),

  importCsv: async (
    file: File,
    source: string = "broker_csv"
  ): Promise<ApiResponse<{ source: string; received: number; saved: number; skipped: number; errors: string[] }>> => {
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await authenticatedFetch(
        `/api/v1/properties/import/csv?source=${encodeURIComponent(source)}`,
        { method: "POST", body: form }
      );
      const body = await r.json();
      if (!r.ok) {
        return { error: body.detail || "Import failed" };
      }
      return { data: body };
    } catch {
      return { error: "Network error" };
    }
  },
};

// Market data APIs (DLD comps map)
export interface DldTransaction {
  transaction_id: string;
  area: string;
  property_type: string;
  rooms?: number | null;
  size_sqft?: number | null;
  amount_aed: number;
  price_per_sqft?: number | null;
  transaction_date: string;
  lat?: number | null;
  lng?: number | null;
  is_demo_data: boolean;
}

export interface Community {
  name: string;
  lat: number;
  lng: number;
  median_price_per_sqft: number | null;
  typical_type: string;
}

export interface CompsResult {
  area: string;
  mode: string;
  sample_size: number;
  median_amount_aed: number;
  median_price_per_sqft: number;
  asking_price_aed: number;
  asking_price_per_sqft?: number;
  basis: "price_per_sqft" | "total_price";
  caveat?: string;
  delta_pct: number;
  verdict: "below_market" | "in_line" | "above_market" | "no_comparable_data";
}

export const marketApi = {
  transactions: (params?: { area?: string; property_type?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.area) query.append("area", params.area);
    if (params?.property_type) query.append("property_type", params.property_type);
    if (params?.limit) query.append("limit", params.limit.toString());
    return fetchApi<{
      mode: string;
      is_demo_data: boolean;
      source: string;
      count: number;
      transactions: DldTransaction[];
    }>(`/api/v1/market/transactions?${query.toString()}`);
  },

  communities: () => fetchApi<{ communities: Community[] }>("/api/v1/market/communities"),

  comps: (params: { area: string; price: number; size_sqft?: number }) => {
    const query = new URLSearchParams({
      area: params.area,
      price: params.price.toString(),
    });
    if (params.size_sqft) query.append("size_sqft", params.size_sqft.toString());
    return fetchApi<CompsResult>(`/api/v1/market/comps?${query.toString()}`);
  },
};

// Workflow APIs (fixed templates — there is no visual builder by design)
export interface WorkflowAction {
  template: string;
  action: string;
  subject_id: string;
  subject_type: string;
  message?: string | null;
  recipient?: string | null;
  reason: string;
  metadata: Record<string, unknown>;
}

export interface OutboxMessage {
  id: string;
  to: string;
  body: string;
  lead_id?: string | null;
  mode: string;
  status: "queued" | "sent" | "failed" | "simulated";
  error?: string | null;
  created_at: string;
}

export interface RefreshSuggestion {
  property_id: string;
  title: string;
  description: string;
  days_stale: number;
  variant: number;
  angle: string;
  price_note?: string | null;
  area?: string;
  price?: number;
  posts_automatically: false;
}

export const workflowsApi = {
  templates: () =>
    fetchApi<{
      builder_enabled: boolean;
      note: string;
      templates: { id: string; label: string; enabled: boolean }[];
      settings: Record<string, number>;
      voice_gate: {
        outbound_enabled: boolean;
        requires_human_approval: boolean;
        note: string;
      };
    }>("/api/v1/workflows/templates"),

  preview: () =>
    fetchApi<{
      evaluated_at: string;
      total_actions: number;
      by_template: Record<string, number>;
      actions: WorkflowAction[];
    }>("/api/v1/workflows/preview"),

  outbox: (leadId?: string) =>
    fetchApi<{
      mode: string;
      delivered: boolean;
      count: number;
      messages: OutboxMessage[];
    }>(`/api/v1/workflows/outbox${leadId ? `?lead_id=${leadId}` : ""}`),

  listingRefresh: () =>
    fetchApi<{
      count: number;
      stale_threshold_days: number;
      suggestions: RefreshSuggestion[];
    }>("/api/v1/workflows/listing-refresh"),

  run: () => fetchApi<Record<string, number>>("/api/v1/workflows/run", { method: "POST" }),
};

// Conversation APIs
export const conversationsApi = {
  getByLead: (leadId: string) => fetchApi(`/api/v1/conversations/${leadId}`),

  create: (leadId: string, data: any) =>
    fetchApi(`/api/v1/conversations/${leadId}`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// Voice WebSocket
export interface AreaAnswer {
  community_id: string;
  name_en: string;
  name_ar: string;
  lat: number;
  lng: number;
  listing_count: number;
  median_price: number | null;
  median_price_psf: number | null;
  travel: {
    to_id: string;
    to_name_en: string;
    to_name_ar: string;
    to_lat: number;
    to_lng: number;
    minutes: number;
    km: number;
    method: string;
    approx: boolean;
  }[];
}

export interface LeadIngestInput {
  source: string;
  first_name?: string;
  phone?: string;
  email?: string;
  preferred_language?: "en" | "ar";
  budget_min?: number;
  budget_max?: number;
  property_type?: string;
  area_preference?: string[];
  timeline?: string;
  message?: string;
}

/** Mirrors backend `MessageResponse` (api/leads.py). */
export interface LeadMessageResponse {
  lead_id: string;
  response: string;
  move: string;
  stage: string;
  score: number;
  band: string;
  score_reasons: string[];
  needs_human: boolean;
  handoff_id: string | null;
  matched_properties: PropertyCardDto[];
  area: AreaAnswer | null;
  compare: Record<string, unknown>[];
  profile: Record<string, unknown>;
  ended: boolean;
  language: "en" | "ar";
  fallbacks: string[];
  latency_ms: number;
}

export interface PropertyCardDto {
  property_id: string;
  title: string;
  price: number | null;
  area: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  size_sqft: number | null;
  image: string | null;
  lat: number | null;
  lng: number | null;
  match_reasons: string[];
}

export type VoiceServerMessage =
  | { type: "ready"; session_id: string; resumed: boolean; tts: boolean; heartbeat_s: number; reply: string; history?: { role: string; text: string; created_at?: string }[] }
  | { type: "transcript"; turn_id: string; text: string; confidence: number | null }
  | { type: "thinking"; turn_id: string }
  | {
      type: "reply";
      turn_id: string;
      user_text: string;
      reply: string;
      spoken_text: string;
      move?: string;
      stage?: string;
      score?: number;
      properties?: PropertyCardDto[];
      area?: AreaAnswer | null;
      language?: "en" | "ar";
      handoff_id?: string | null;
      ended?: boolean;
      interrupted?: boolean;
      fallbacks: string[];
      audio?: string;
      audio_format?: string;
      stt_error?: string;
    }
  | { type: "cancelled"; turn_id: string }
  | { type: "error"; turn_id?: string; code: string; recoverable: boolean }
  | { type: "ping" }
  | { type: "pong" };

/**
 * Voice WS v2 client: every utterance carries a turn_id, `interrupt()` cancels the
 * in-flight turn (barge-in), heartbeats are answered, and dropped sockets are
 * re-opened with the same session_id so the server can replay the transcript.
 */
export class VoiceWebSocket {
  private ws: WebSocket | null = null;
  private leadId: string;
  private onMessage: (data: VoiceServerMessage) => void;
  private onError: (error: unknown) => void;
  private sessionId: string | null = null;
  private closed = false; // terminal: a disconnected instance never reopens
  private retries = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  currentTurnId: string | null = null;

  constructor(
    leadId: string,
    onMessage: (data: VoiceServerMessage) => void,
    onError: (error: unknown) => void
  ) {
    this.leadId = leadId;
    this.onMessage = onMessage;
    this.onError = onError;
  }

  async connect() {
    let token: string | undefined;
    try {
      const { data } = await createClient().auth.getSession();
      token = data.session?.access_token;
    } catch {
      token = undefined;
    }
    const workspaceId = localStorage.getItem("active_workspace_id");

    if (!token && !DEMO_MODE) {
      this.onError(new Error("Authentication required"));
      return;
    }

    const wsUrl = API_BASE.replace("http", "ws");
    const query = new URLSearchParams();
    if (token) query.set("token", token);
    if (workspaceId) query.set("workspace_id", workspaceId);
    if (this.sessionId) query.set("session_id", this.sessionId);
    if (this.closed) return; // disconnect() raced the auth lookup above
    this.ws = new WebSocket(`${wsUrl}/api/v1/voice/conversation/${this.leadId}?${query}`);

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as VoiceServerMessage;
      if (data.type === "ping") {
        this.send({ type: "pong" });
        return;
      }
      if (data.type === "ready") {
        this.sessionId = data.session_id;
        this.retries = 0;
      }
      if (data.type === "reply" || data.type === "cancelled") {
        if (this.currentTurnId === data.turn_id) this.currentTurnId = null;
      }
      this.onMessage(data);
    };

    this.ws.onerror = (error) => {
      this.onError(error);
    };

    this.ws.onclose = (event) => {
      // 44xx codes are auth/lookup rejections; anything else is a drop we resume from.
      if (this.closed || (event.code >= 4400 && event.code < 4500) || this.retries >= 5) return;
      const delay = Math.min(8000, 500 * 2 ** this.retries++);
      this.reconnectTimer = setTimeout(() => void this.connect(), delay);
    };
  }

  private send(payload: Record<string, unknown>): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(payload));
    return true;
  }

  private newTurn(): string {
    const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    this.currentTurnId = id;
    return id;
  }

  sendAudio(audioBase64: string): string | null {
    const turnId = this.newTurn();
    return this.send({ type: "audio", data: audioBase64, turn_id: turnId }) ? turnId : null;
  }

  sendText(text: string, wantAudio = false): string | null {
    const turnId = this.newTurn();
    return this.send({ type: "text", text, turn_id: turnId, want_audio: wantAudio }) ? turnId : null;
  }

  /** Barge-in: cancel whatever the server is doing for the current turn. */
  interrupt() {
    if (this.currentTurnId) this.send({ type: "interrupt", turn_id: this.currentTurnId });
    this.currentTurnId = null;
  }

  disconnect() {
    this.closed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}

// Broker workspace (Broker Today, pipeline, lead detail) — /api/v1/broker
export interface BrokerLeadSummary {
  id: string;
  name: string;
  phone: string | null;
  language: string;
  score: number;
  band: string | null;
  stage: string;
  purpose: string | null;
  budget_min_aed: number | null;
  budget_max_aed: number | null;
  budget_period: string | null;
  areas: string[];
  property_type: string | null;
  timeline: string | null;
  source: string | null;
  assigned_broker: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BrokerHandoff {
  id: string;
  lead_id: string;
  broker_id: string | null;
  broker_name: string | null;
  status: "pending" | "accepted" | "declined" | "escalated" | "expired" | string;
  reason: string | null;
  score: number | null;
  band: string | null;
  language: string | null;
  slot_text: string | null;
  created_at: string | null;
  reassign_after: string | null;
  accepted_at: string | null;
  reassigned_count: number | null;
  routing_reasons: string[] | null;
  decline_reason: string | null;
}

export interface BrokerBrief {
  headline: string;
  band: string;
  score: number;
  next_step: string;
  facts?: Record<string, unknown>;
  objections?: string[];
  liked?: string[];
  disliked?: string[];
  score_reasons?: string[];
  [key: string]: unknown;
}

export interface BrokerFollowup {
  id: string;
  lead_id: string;
  touch: number;
  template_key: string;
  due_at: string;
  status: string;
  lead_name?: string;
  lead_band?: string | null;
}

export interface BrokerToday {
  date: string;
  broker_id: string | null;
  counts: {
    new_handoffs: number;
    accepted: number;
    hot_leads: number;
    viewings: number;
    followups_due: number;
    escalated: number;
  };
  new_handoffs: { handoff: BrokerHandoff; lead: BrokerLeadSummary | null }[];
  accepted_handoffs: { handoff: BrokerHandoff; lead: BrokerLeadSummary | null }[];
  hot_leads: BrokerLeadSummary[];
  viewings: Record<string, unknown>[];
  followups: BrokerFollowup[];
  escalated: { handoff: BrokerHandoff; lead: BrokerLeadSummary | null }[];
}

export interface BrokerPipeline {
  broker_id: string | null;
  stages: { stage: string; count: number; leads: BrokerLeadSummary[] }[];
}

export type TimelineItem =
  | { at: string | null; kind: "event"; type: string; payload: Record<string, unknown> | null }
  | { at: string | null; kind: "change"; field: string; old: unknown; new: unknown; by: string | null }
  | { at: string | null; kind: "message"; role: string; text: string; channel: string | null };

export interface BrokerLeadDetail {
  lead: BrokerLeadSummary & {
    email?: string | null;
    payment?: string | null;
    bedrooms_min?: number | null;
    score_reasons?: string[] | null;
    consent?: Record<string, unknown> | null;
    notes?: string | null;
    initial_message?: string | null;
    community_ids?: string[] | null;
    property_types?: string[] | null;
  };
  brief: BrokerBrief | null;
  handoff: BrokerHandoff | null;
  sources: Record<string, unknown>[];
  followups: BrokerFollowup[];
  timeline: TimelineItem[];
}

export interface LeadPatch {
  purpose?: string;
  budget_min_aed?: number;
  budget_max_aed?: number;
  budget_period?: string;
  community_ids?: string[];
  property_types?: string[];
  timeline?: string;
  payment?: string;
  stage?: string;
  notes?: string;
}

const withBroker = (path: string, brokerId?: string | null) =>
  brokerId ? `${path}?broker_id=${encodeURIComponent(brokerId)}` : path;

export const brokerApi = {
  today: (brokerId?: string | null) => fetchApi<BrokerToday>(withBroker("/api/v1/broker/today", brokerId)),
  pipeline: (brokerId?: string | null) =>
    fetchApi<BrokerPipeline>(withBroker("/api/v1/broker/pipeline", brokerId)),
  lead: (id: string) => fetchApi<BrokerLeadDetail>(`/api/v1/broker/leads/${id}`),
  patchLead: (id: string, patch: LeadPatch) =>
    fetchApi<{ lead: BrokerLeadSummary; changed: string[] }>(`/api/v1/broker/leads/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  accept: (handoffId: string, brokerId?: string | null) =>
    fetchApi<BrokerHandoff>(`/api/v1/broker/handoffs/${handoffId}/accept`, {
      method: "POST",
      body: JSON.stringify(brokerId ? { broker_id: brokerId } : {}),
    }),
  decline: (handoffId: string, input: { broker_id?: string | null; reason?: string }) =>
    fetchApi<BrokerHandoff>(`/api/v1/broker/handoffs/${handoffId}/decline`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  followups: (brokerId?: string | null) =>
    fetchApi<BrokerFollowup[]>(withBroker("/api/v1/broker/followups", brokerId)),
};

// Admin: connectors, field maps, review queue, data health — /api/v1/admin
export interface Connector {
  id: string;
  type: string;
  mode: "pull" | "push";
  display_name: string;
  status: "active" | "paused" | "disabled";
  schedule_seconds: number | null;
  config: Record<string, unknown>;
  has_secret: boolean;
  secret?: string;
  webhook_path?: string;
  cursor?: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  created_at?: string;
}

export interface FieldMapEntry {
  source_field: string;
  target_field: string | null;
  transform?: string | null;
  confidence?: number;
  approved_at?: string | null;
}

export interface ReviewItem {
  id: string;
  raw_record_id: string;
  reason: string;
  status: string;
  suggested_fix: Record<string, unknown> | null;
  draft: Record<string, unknown> | null;
  payload: Record<string, unknown> | null;
  record_status: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface DataHealth {
  connectors: {
    connector_id: string;
    type: string;
    display_name: string | null;
    status: string | null;
    consecutive_failures: number;
    last_run_at: string | null;
    last_success_at: string | null;
    records: number;
    published: number;
    review: number;
    error: number;
    publish_rate: number | null;
    [key: string]: unknown;
  }[];
  totals: Record<string, number>;
  review_open: number;
  events_total: number;
}

export interface CsvUploadResult {
  connector_id: string;
  rows: number;
  landed: number;
  duplicates: number;
  headers: string[];
  field_map_suggestions: FieldMapEntry[];
  processed: number;
  published: number;
  created: number;
  review: number;
}

export const adminApi = {
  connectors: () => fetchApi<Connector[]>("/api/v1/admin/connectors"),
  createConnector: (input: {
    type: string;
    display_name?: string;
    schedule_seconds?: number;
    config?: Record<string, unknown>;
    credential?: string;
  }) =>
    fetchApi<Connector>("/api/v1/admin/connectors", { method: "POST", body: JSON.stringify(input) }),
  patchConnector: (
    id: string,
    patch: { status?: Connector["status"]; rotate_secret?: boolean; credential?: string; schedule_seconds?: number }
  ) => fetchApi<Connector>(`/api/v1/admin/connectors/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  runConnector: (id: string) =>
    fetchApi<{ fetched?: number; landed?: number; processed: number; published: number; error?: string }>(
      `/api/v1/admin/connectors/${id}/run`,
      { method: "POST" }
    ),
  fieldMap: (id: string) =>
    fetchApi<{ connector_id: string; approved: FieldMapEntry[]; suggested: FieldMapEntry[] }>(
      `/api/v1/admin/connectors/${id}/field-map`
    ),
  putFieldMap: (id: string, mappings: FieldMapEntry[]) =>
    fetchApi<{ connector_id: string; approved: number }>(`/api/v1/admin/connectors/${id}/field-map`, {
      method: "PUT",
      body: JSON.stringify({ mappings: mappings.map(({ source_field, target_field, transform }) => ({ source_field, target_field, transform })) }),
    }),
  reviewQueue: (resolved = false) =>
    fetchApi<ReviewItem[]>(`/api/v1/admin/review-queue?resolved=${resolved}`),
  resolveReview: (id: string, input: { action: "retry" | "discard"; fixed_payload?: Record<string, unknown> }) =>
    fetchApi<{ status: string; lead_id?: string | null }>(`/api/v1/admin/review-queue/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  retryErrors: () =>
    fetchApi<{ retried: number; published: number }>("/api/v1/admin/pipeline/retry-errors", { method: "POST" }),
  dataHealth: () => fetchApi<DataHealth>("/api/v1/admin/data-health"),
  uploadCsv: async (file: File, connectorId?: string): Promise<ApiResponse<CsvUploadResult>> => {
    const form = new FormData();
    form.append("file", file);
    const query = connectorId ? `?connector_id=${encodeURIComponent(connectorId)}` : "";
    try {
      const r = await authenticatedFetch(`/api/v1/ingest/csv${query}`, { method: "POST", body: form });
      const body = await r.json().catch(() => null);
      if (!r.ok) return { error: normalizeApiError(body) };
      return { data: body };
    } catch {
      return { error: "Network error" };
    }
  },
};
