export interface ToolStep {
  id: string;
  tool: string;
  query?: string;
  ms?: number;
  count?: number;
  done: boolean;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
  /** true while an answer is actively streaming in (drives caret + hides actions) */
  stream?: boolean;
  /** agent tool calls surfaced in the UI (rich streaming) */
  steps?: ToolStep[];
}
