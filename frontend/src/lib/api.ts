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

  /**
   * Ask a question and stream the answer. `onToken` is called with each text
   * chunk as it arrives.
   */
  async ask(request: AskRequest, onToken: (chunk: string) => void): Promise<void> {
    const res = await fetch(`${this.baseUrl}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!res.ok || !res.body) throw new Error(`API error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) onToken(decoder.decode(value, { stream: true }));
    }
  }
}

export const apiClient = new NoorApiClient();
