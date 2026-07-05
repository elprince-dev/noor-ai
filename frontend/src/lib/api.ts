const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type School = "hanafi" | "maliki" | "shafii" | "hanbali" | "general";

export interface AskRequest {
  question: string;
  session_id: string;
  school: School;
}

export interface AskResponse {
  answer: string;
  session_id: string;
}

export interface SessionResponse {
  session_id: string;
}

export class NoorApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl;
  }

  async createSession(): Promise<SessionResponse> {
    const res = await fetch(`${this.baseUrl}/sessions`, { method: "POST" });
    if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
    return res.json();
  }

  async ask(request: AskRequest): Promise<AskResponse> {
    const res = await fetch(`${this.baseUrl}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  }
}

export const apiClient = new NoorApiClient();
