import { assertFleetMindResponse, fleetMindRequest } from "./api";

export type Conversation = {
  id: string;
  title: string;
  archived: boolean;
  asset_id: string | null;
  prediction_id: number | null;
  created_at: string;
  updated_at: string;
};
export type ConversationPage = { items: Conversation[]; next_offset: number | null };
export type Scope = Pick<Conversation, "asset_id" | "prediction_id">;
export type Citation = {
  id: string;
  kind: "asset" | "prediction" | "explanation" | "model" | "knowledge";
  title: string;
  asset_id: string | null;
  prediction_id: number | null;
  document_id: string | null;
  chunk_id: string | null;
  source_ref: string | null;
  section: string | null;
};
export type Answer = {
  answer: string;
  status: "answered" | "clarification_required" | "insufficient_evidence" | "unavailable";
  citations: Citation[];
  facts: { id: string; text: string; citation: Citation }[];
  next_steps: string[];
  limitations: string[];
  diagnostics: {
    elapsed_ms: number;
    tool_count: number;
    provider_calls: number;
    tool_names: string[];
    issues: string[];
    tokens: { input: number; output: number } | null;
  };
};
export type MessageState = "pending" | "completed" | "cancelled" | "failed";
export type Message = Scope & {
  id: number;
  request_id: string;
  role: "user" | "assistant";
  state: MessageState;
  content: string;
  response: Answer | null;
  provider: string | null;
  model: string | null;
  created_at: string;
};
export type MessagePage = { items: Message[]; next_before_id: number | null };
export type ProviderStatus = {
  configured: boolean;
  provider: string;
  model: string | null;
  detail: string;
  reason: "configured" | "disabled" | "credentials_missing" | "invalid_configuration";
  embedding_state: "cold" | "initializing" | "ready" | "unavailable";
};
export type KnowledgeStatus = { state: "ready" | "empty" | "unavailable"; documents: number; chunks: number };
export type StreamEvent = { request_id: string } & (
  | { type: "started"; user: Message }
  | { type: "tool_started"; tool: string }
  | { type: "tool_completed"; tool: string; outcome: "ok" | "error" }
  | { type: "evidence"; count: number }
  | { type: "final"; message: Message }
  | { type: "cancelled" | "error"; detail: string }
  | { type: "clarification" | "completed" }
);

export const CONVERSATIONS = "copilot/conversations";
export const UUID_PATTERN = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
export const QUESTION_LIMIT = 1200;
export const EMPTY_SCOPE: Scope = { asset_id: null, prediction_id: null };

export function copilotHref(assetId?: string | null, predictionId?: number | null) {
  const params = new URLSearchParams();
  if (assetId) params.set("asset", assetId);
  if (predictionId) params.set("prediction", String(predictionId));
  return params.size ? `/copilot?${params}` : "/copilot";
}

export function writeJson(method: "POST" | "PATCH", payload: object): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) };
}

export function cancelRequest(conversationId: string, requestId: string, keepalive = false) {
  return fleetMindRequest<{ state: MessageState }>(
    `${CONVERSATIONS}/${conversationId}/requests/${requestId}/cancel`, { method: "POST", keepalive },
  );
}

export async function streamReply(
  conversationId: string, requestId: string, question: string,
  signal: AbortSignal, onEvent: (event: StreamEvent) => void,
) {
  const response = await fetch(`/api/fleetmind/${CONVERSATIONS}/${conversationId}/messages/stream`, {
    ...writeJson("POST", { request_id: requestId, question }),
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" }, signal,
  });
  await assertFleetMindResponse(response);
  if (!response.body || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
    throw new Error("The response stream is unavailable.");
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let finished = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;
      let end = buffer.indexOf("\n\n");
      while (end >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = frame.split("\n").find((line) => line.startsWith("data: "));
        if (data) {
          const event = JSON.parse(data.slice(6)) as StreamEvent;
          if (event.request_id === requestId && !signal.aborted) {
            onEvent(event);
            finished ||= event.type === "completed" || event.type === "cancelled" || event.type === "error";
          }
        }
        end = buffer.indexOf("\n\n");
      }
    }
    if (!finished) throw new Error("The connection closed before FleetMind confirmed the result.");
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
