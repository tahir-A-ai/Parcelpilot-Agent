// ============================================================
// API client for ParcelPilot backend
// ============================================================

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

export interface ToolLog {
  step: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  observations: string;
}

export interface StagedAction {
  action_id: string;
  status: string;
  summary?: string;
  action_type?: string;
  payload?: Record<string, unknown>;
  // Raw from tool observations
  [key: string]: unknown;
}

export interface ChatResponse {
  reply: string;
  tool_logs: ToolLog[];
  staged_action: StagedAction | null;
}

export interface ConfirmResponse {
  message: string;
}

export interface StreamCallbacks {
  onToolStart?: (toolName: string, step: number) => void;
  onToolEnd?: (tool: ToolLog) => void;
  onToken?: (token: string) => void;
  onDone?: (data: ChatResponse) => void;
  onError?: (err: Error) => void;
}

export function cleanErrorMessage(raw: string): string {
  if (!raw) return "An unexpected error occurred. Please try again.";

  const lower = raw.toLowerCase();
  if (lower.includes("10054") || lower.includes("forcibly closed") || lower.includes("connection reset")) {
    return "The AI service connection was temporarily interrupted. Please try sending your message again.";
  }
  if (lower.includes("rate_limit") || lower.includes("429") || lower.includes("tokens per minute") || lower.includes("tpm")) {
    return "The AI service is experiencing high traffic. Please wait a moment and try again.";
  }
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return "The request timed out. Please try sending your message again.";
  }
  if (lower.includes("failed to fetch") || lower.includes("networkerror")) {
    return "Unable to reach the ParcelPilot server. Please ensure the backend service is running.";
  }
  if (lower.includes("groqexception") || lower.includes("litellm") || lower.includes("error while generating")) {
    return "The AI service encountered a temporary processing issue. Please try again.";
  }
  return raw;
}

export async function sendMessage(
  account_id: string,
  message: string,
  session_id: string,
  history: Array<{ role: string; content: string }> = []
): Promise<ChatResponse> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id, message, session_id, history }),
    });
  } catch (netErr) {
    throw new Error(cleanErrorMessage(netErr instanceof Error ? netErr.message : "Failed to fetch"));
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const rawDetail = typeof err.detail === "string" ? err.detail : "Agent request failed";
    throw new Error(cleanErrorMessage(rawDetail));
  }

  const json = await res.json();
  return json.data as ChatResponse;
}

export async function streamMessage(
  account_id: string,
  message: string,
  session_id: string,
  history: Array<{ role: string; content: string }> = [],
  callbacks: StreamCallbacks
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id, message, session_id, history }),
    });
  } catch (netErr) {
    const cleaned = cleanErrorMessage(netErr instanceof Error ? netErr.message : "Failed to fetch");
    callbacks.onError?.(new Error(cleaned));
    return;
  }

  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const rawDetail = typeof err.detail === "string" ? err.detail : "Agent request failed";
    callbacks.onError?.(new Error(cleanErrorMessage(rawDetail)));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";

      for (const block of blocks) {
        const line = block.trim();
        if (!line.startsWith("data: ")) continue;
        const jsonStr = line.slice(6).trim();
        if (!jsonStr) continue;

        try {
          const event = JSON.parse(jsonStr);
          if (event.type === "tool_start") {
            callbacks.onToolStart?.(event.tool_name, event.step);
          } else if (event.type === "tool_end") {
            callbacks.onToolEnd?.({
              step: event.step,
              tool_name: event.tool_name,
              arguments: event.arguments || {},
              observations: event.observations || "",
            });
          } else if (event.type === "token") {
            callbacks.onToken?.(event.text || "");
          } else if (event.type === "done") {
            callbacks.onDone?.({
              reply: event.reply || "",
              tool_logs: event.tool_logs || [],
              staged_action: event.staged_action || null,
            });
          } else if (event.type === "error") {
            callbacks.onError?.(new Error(cleanErrorMessage(event.detail || "Service error")));
          }
        } catch {
          // Ignore incomplete JSON frame
        }
      }
    }
  } catch (streamErr) {
    callbacks.onError?.(new Error(cleanErrorMessage(streamErr instanceof Error ? streamErr.message : "Streaming error")));
  }
}

export async function confirmAction(
  session_id: string,
  action_id: string,
  confirmed: boolean
): Promise<ConfirmResponse> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}/action/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, action_id, confirmed }),
    });
  } catch (netErr) {
    throw new Error(cleanErrorMessage(netErr instanceof Error ? netErr.message : "Failed to fetch"));
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const rawDetail = typeof err.detail === "string" ? err.detail : "Confirmation failed";
    throw new Error(cleanErrorMessage(rawDetail));
  }

  const json = await res.json();
  return json.data as ConfirmResponse;
}
