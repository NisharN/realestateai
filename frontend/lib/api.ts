"use client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiResponse<T> {
  data?: T;
  error?: string;
}

async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "An error occurred" };
    }

    const data = await response.json();
    return { data };
  } catch (error) {
    return { error: "Network error" };
  }
}

// Lead APIs
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
    return fetchApi(`/api/v1/leads/?${query.toString()}`);
  },

  getById: (id: string) => fetchApi(`/api/v1/leads/${id}`),

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

  connect() {
    const wsUrl = API_BASE.replace("http", "ws");
    this.ws = new WebSocket(`${wsUrl}/api/v1/voice/conversation/${this.leadId}`);

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
