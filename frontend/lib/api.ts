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

interface ApiResponse<T> {
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
  ingest: (leadData: any) =>
    fetchApi("/api/v1/leads/ingest", {
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

  sendMessage: (id: string, message: { text: string }) =>
    fetchApi(`/api/v1/leads/${id}/message`, {
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

  scrapeBayut: (params?: { property_type?: string; area?: string; pages?: number }) =>
    fetchApi("/api/v1/properties/scrape/bayut", {
      method: "POST",
      body: JSON.stringify(params),
    }),

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
export class VoiceWebSocket {
  private ws: WebSocket | null = null;
  private leadId: string;
  private onMessage: (data: any) => void;
  private onError: (error: any) => void;

  constructor(
    leadId: string,
    onMessage: (data: any) => void,
    onError: (error: any) => void
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
    this.ws = new WebSocket(`${wsUrl}/api/v1/voice/conversation/${this.leadId}?${query}`);

    this.ws.onopen = () => {
      console.log("Voice WebSocket connected");
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.onMessage(data);
    };

    this.ws.onerror = (error) => {
      this.onError(error);
    };

    this.ws.onclose = () => {
      console.log("Voice WebSocket closed");
    };
  }

  sendAudio(audioBase64: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: "audio",
          data: audioBase64,
        })
      );
    }
  }

  sendText(text: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: "text",
          text,
        })
      );
    }
  }

  disconnect() {
    this.ws?.close();
  }
}
