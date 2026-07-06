// Every endpoint is under /api. In production the origin is empty, so calls go
// to /api/* on the same domain (CloudFront routes /api/* → API Gateway).
// Locally, NEXT_PUBLIC_API_URL points at the backend host (e.g. http://localhost:8000).
const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL || '';

export type School = 'hanafi' | 'maliki' | 'shafii' | 'hanbali' | 'general';

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

  constructor(origin: string = API_ORIGIN) {
    this.baseUrl = `${origin}/api`;
  }

  async createSession(): Promise<SessionResponse> {
    const res = await fetch(`${this.baseUrl}/sessions`, { method: 'POST' });
    if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
    return res.json();
  }

  async ask(request: AskRequest): Promise<AskResponse> {
    const res = await fetch(`${this.baseUrl}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  }
}

export const apiClient = new NoorApiClient();
