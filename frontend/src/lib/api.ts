// Every endpoint is under /api. In production the origin is empty, so calls go
// to /api/* on the same domain (CloudFront routes /api/* → API Gateway).
// Locally, NEXT_PUBLIC_API_URL points at the backend host (e.g. http://localhost:8000).
const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL || '';

export type School = 'hanafi' | 'maliki' | 'shafii' | 'hanbali' | 'general';

export type AgentStreamEvent =
  | { type: "token"; text: string }
  | { type: "tool_start"; id: string; tool: string; query?: string }
  | { type: "tool_end"; id: string; tool: string; ms: number; count: number }
  | { type: "done" }
  | { type: "error"; detail: string };

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
   * Ask a question and stream structured agent events (NDJSON). `onEvent` is
   * called for each event: tool_start/tool_end (agent steps), token (answer
   * text), done, error.
   */
  async ask(
    request: AskRequest,
    onEvent: (event: AgentStreamEvent) => void,
  ): Promise<void> {
    const res = await fetch(`${this.baseUrl}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!res.ok || !res.body) throw new Error(`API error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const flushLines = (final = false) => {
      let idx: number;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (line) onEvent(JSON.parse(line));
      }
      if (final) {
        const rest = buffer.trim();
        if (rest) onEvent(JSON.parse(rest));
      }
    };

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      flushLines();
    }
    flushLines(true);
  }
}

export const apiClient = new NoorApiClient();
