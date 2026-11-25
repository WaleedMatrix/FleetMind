"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Activity, Archive, ArrowLeft, ArrowRight, ArrowUp, BookOpen, ChevronDown, CircleAlert,
  Factory, History, Loader2, MessageSquare, PanelLeft, Pencil, Plus, Radio, RotateCcw,
  Search, ShieldCheck, Sparkles, Square, Trash2, Zap,
} from "lucide-react";
import { fleetMindRequest } from "@/lib/api";
import { assetPath, type Asset } from "@/lib/assets";
import {
  cancelRequest, CONVERSATIONS, EMPTY_SCOPE, QUESTION_LIMIT, streamReply, UUID_PATTERN, writeJson,
  type Citation, type Conversation, type ConversationPage, type KnowledgeStatus, type Message,
  type MessagePage, type ProviderStatus, type Scope, type StreamEvent,
} from "@/lib/copilot";
import { predictionLabel, timestampLabel } from "@/lib/predictions";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";
import { AssetPicker } from "./asset-picker";
import { CopilotEvidence, SourceDrawer } from "./copilot-evidence";

const QUESTIONS = {
  general: ["What are the model’s limitations?", "How should I review a high-priority alert?", "How do I interpret a SHAP contribution?"],
  asset: (id: string) => [`Show the latest predictions for asset ${id}.`, `What is registered for asset ${id}?`],
  prediction: (id: number) => [`Summarize prediction ${id}.`, `Explain the SHAP contributions for prediction ${id}.`],
};
const TOOLS: Record<string, string> = {
  search_assets: "Search the asset registry",
  get_asset: "Read the selected asset",
  get_asset_history: "Read an asset’s prediction history",
  get_asset_summary: "Read asset monitoring totals",
  list_recent_alerts: "Read recent alerts",
  get_prediction: "Inspect a prediction",
  explain_prediction: "Compute the SHAP explanation",
  get_model_information: "Read verified model evaluation",
  search_knowledge: "Search the knowledge library",
};
const EMBEDDING = {
  cold: "Encoder loads on first semantic search",
  initializing: "Initializing knowledge encoder…",
  ready: "Knowledge encoder ready",
  unavailable: "Knowledge encoder unavailable",
};
const PAGE_SIZE = 20;

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "FleetMind could not complete the request.";
}

function Progress({ events }: { events: string[] }) {
  return <div className="copilot-progress" aria-live="polite" aria-atomic="false">
    {events.length > 0 && <ol>{events.map((event, index) => (
      <li key={index}><Activity size={14} aria-hidden="true" />{event}</li>
    ))}</ol>}
  </div>;
}

function ContextControls({
  scope, onScope, disabled,
}: { scope: Scope; onScope: (scope: Scope) => void; disabled: boolean }) {
  const asset = useFleetMindQuery<Asset>(scope.asset_id ? assetPath(scope.asset_id) : null);
  return <div className="copilot-context">
    <details>
      <summary>
        <Factory size={15} aria-hidden="true" />
        <span>{asset.data?.display_name ?? scope.asset_id ?? "Any asset"}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </summary>
      <fieldset disabled={disabled || (Boolean(scope.asset_id) && asset.pending)}>
        <legend>Conversation asset</legend>
        {asset.error && <p className="copilot-error" role="alert">{asset.error}</p>}
        <AssetPicker value={asset.data} onChange={(choice) => onScope({
          asset_id: choice?.asset_id ?? null,
          prediction_id: choice?.asset_id === scope.asset_id ? scope.prediction_id : null,
        })} />
        {asset.error && <button type="button" className="copilot-button"
          onClick={() => onScope(EMPTY_SCOPE)}>Clear asset context</button>}
      </fieldset>
    </details>
    {scope.prediction_id && (
      <button type="button" className="copilot-button copilot-prediction-chip" disabled={disabled}
        onClick={() => onScope({ ...scope, prediction_id: null })}>
        <Activity size={15} aria-hidden="true" /> Prediction {predictionLabel(scope.prediction_id)}
        <span aria-hidden="true">×</span><span className="copilot-sr-only">Clear prediction context</span>
      </button>
    )}
  </div>;
}

function Readiness({
  provider, knowledge, error, onRetry,
}: { provider: ProviderStatus | null; knowledge: KnowledgeStatus | null; error: string | null; onRetry: () => void }) {
  return <div className="copilot-readiness" aria-live="polite">
    <span className="copilot-status">
      <i data-ready={provider?.configured === true} />
      {error ? "Provider readiness unavailable" : !provider ? "Checking provider…" : provider.configured
        ? provider.provider === "local_evidence" ? "Local evidence search"
          : provider.provider === "mock" ? "Mock provider" : "Provider configured"
        : provider.detail}
    </span>
    {provider?.model && <span className="copilot-provider-model">{provider.model}</span>}
    {error && <button type="button" className="copilot-text-button" onClick={onRetry}>Check again</button>}
    {knowledge?.state === "empty" && <span><BookOpen size={14} aria-hidden="true" /> Knowledge base empty</span>}
    {knowledge?.state === "unavailable" && <span><BookOpen size={14} aria-hidden="true" /> Knowledge storage unavailable</span>}
    {provider && <span><Radio size={14} aria-hidden="true" />{EMBEDDING[provider.embedding_state]}</span>}
  </div>;
}

function ConversationList({
  selected, revision, onSelect, onNew, expanded, onToggle, onError,
}: {
  selected: string | null; revision: number; onSelect: (id: string) => void; onNew: () => void;
  expanded: boolean; onToggle: () => void; onError: (message: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [extra, setExtra] = useState<{ key: string; items: Conversation[]; next: number | null }>();
  const [loadingMore, setLoadingMore] = useState(false);
  const filter = new URLSearchParams({ q: search.trim(), archived: String(archived), limit: String(PAGE_SIZE) });
  const key = `${filter}:${revision}`;
  const history = useFleetMindQuery<ConversationPage>(`${CONVERSATIONS}?${filter}`, { delay: 150, revision });
  const items = [...new Map([
    ...(history.data?.items ?? []), ...(extra?.key === key ? extra.items : []),
  ].map((item) => [item.id, item])).values()];
  const next = extra?.key === key ? extra.next : history.data?.next_offset ?? null;

  async function loadMore() {
    if (next === null) return;
    setLoadingMore(true);
    try {
      filter.set("offset", String(next));
      const page = await fleetMindRequest<ConversationPage>(`${CONVERSATIONS}?${filter}`);
      setExtra((previous) => ({
        key, items: [...(previous?.key === key ? previous.items : []), ...page.items], next: page.next_offset,
      }));
    } catch (error) { onError(errorText(error)); }
    finally { setLoadingMore(false); }
  }

  return <aside className="copilot-sidebar" data-expanded={expanded} aria-label="Conversation history">
    <div className="copilot-sidebar-head">
      <button type="button" className="copilot-mobile-toggle copilot-button" aria-expanded={expanded}
        aria-controls="copilot-history" onClick={onToggle}><PanelLeft size={17} aria-hidden="true" /> History</button>
      <h2><History size={16} aria-hidden="true" /> Conversations</h2>
      <button type="button" className="copilot-button copilot-new" onClick={onNew}>
        <Plus size={17} aria-hidden="true" /> New conversation
      </button>
    </div>
    <div id="copilot-history" className="copilot-history">
      <label className="copilot-search"><Search size={16} aria-hidden="true" />
        <span className="copilot-sr-only">Search conversations</span>
        <input type="search" maxLength={120} value={search}
          onChange={(event) => setSearch(event.target.value)} placeholder="Search conversations" />
      </label>
      <div className="copilot-filters" role="group" aria-label="Conversation status">
        <button type="button" aria-pressed={!archived} onClick={() => setArchived(false)}>Active</button>
        <button type="button" aria-pressed={archived} onClick={() => setArchived(true)}>Archived</button>
      </div>
      {history.error && <p className="copilot-error" role="alert">{history.error}</p>}
      {history.pending && !items.length ? <p className="copilot-muted" role="status">Loading history…</p>
        : !history.error && !items.length ? <p className="copilot-muted">{search
          ? "No conversations match this search." : archived ? "No archived conversations." : "No conversations yet."}</p> : null}
      <ol className="copilot-conversations">
        {items.map((item) => <li key={item.id}>
          <button type="button" aria-current={selected === item.id ? "true" : undefined}
            onClick={() => onSelect(item.id)}>
            <MessageSquare size={16} aria-hidden="true" />
            <span><strong>{item.title}</strong><small>{item.asset_id ?? timestampLabel(item.updated_at)}</small></span>
          </button>
        </li>)}
      </ol>
      {next !== null && <button type="button" className="copilot-button" onClick={() => void loadMore()} disabled={loadingMore}>Load more conversations</button>}
    </div>
  </aside>;
}

type ActiveRequest = { id: string; controller: AbortController };

function ConversationThread({
  conversation, scope, setDraftScope, canSend, onCreate, onChange, onDelete, onHistoryChange,
}: {
  conversation: Conversation | null; scope: Scope; setDraftScope: (scope: Scope) => void;
  canSend: boolean; onCreate: (scope: Scope) => Promise<Conversation>;
  onChange: (conversation: Conversation) => void; onDelete: () => void; onHistoryChange: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [problem, setProblem] = useState("");
  const [notice, setNotice] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [older, setOlder] = useState<MessagePage | null>(null);
  const [overlay, setOverlay] = useState<Message[]>([]);
  const [source, setSource] = useState<Citation | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const renameButton = useRef<HTMLButtonElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const active = useRef<ActiveRequest | null>(null);
  const mounted = useRef(true);
  const id = conversation?.id;
  const path = id ? `${CONVERSATIONS}/${id}` : null;
  const thread = useFleetMindQuery<MessagePage>(path ? `${path}/messages` : null, { revision });
  const saved = new Map((older?.items ?? []).map((message) => [message.id, message]));
  for (const message of thread.data?.items ?? []) saved.set(message.id, message);
  for (const message of overlay) saved.set(message.id, message);
  const messages = [...saved.values()].sort((a, b) => a.id - b.id);
  const olderCursor = older ? older.next_before_id : thread.data?.next_before_id ?? null;
  const pending = messages.find((message) => message.state === "pending");
  const working = workingId !== null;
  const stoppableId = workingId ?? pending?.request_id;
  const locked = busy || working || Boolean(pending) || Boolean(id && thread.pending && !thread.data);
  const suggestions = scope.prediction_id ? QUESTIONS.prediction(scope.prediction_id)
    : scope.asset_id ? QUESTIONS.asset(scope.asset_id) : QUESTIONS.general;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const request = active.current;
      active.current = null;
      if (!request) return;
      request.controller.abort();
      if (id) void cancelRequest(id, request.id, true).catch(() => undefined);
    };
  }, [id]);

  function showProgress(event: StreamEvent) {
    switch (event.type) {
      case "started":
        setOverlay([event.user]);
        setEvents(["Request started"]);
        break;
      case "tool_started":
        setEvents((previous) => [...previous, TOOLS[event.tool] ?? "Run a read-only tool"]);
        break;
      case "tool_completed":
        setEvents((previous) => [...previous, event.outcome === "ok" ? "Tool completed" : "Tool unavailable"]);
        break;
      case "evidence":
        setEvents((previous) => [...previous, `${event.count} evidence items retrieved`]);
        break;
      case "clarification":
        setEvents((previous) => [...previous, "Clarification needed"]);
        break;
      case "final":
        setOverlay((previous) => [...previous.map((message): Message => ({ ...message, state: "completed" })), event.message]);
        break;
      case "completed":
        setNotice("Response ready");
        break;
      case "cancelled":
        setOverlay((previous) => previous.map((message) => ({ ...message, state: "cancelled" })));
        setEvents((previous) => [...previous, event.detail]);
        break;
      case "error":
        setProblem(event.detail);
        break;
    }
  }

  function refreshThread() {
    setRevision((count) => count + 1);
    onHistoryChange();
  }

  function closeRename() {
    setRenaming(false);
    requestAnimationFrame(() => renameButton.current?.focus());
  }

  async function send(value: string) {
    const text = value.trim();
    if (!text || !id || locked || active.current || !canSend || conversation.archived) return;
    const request: ActiveRequest = { id: crypto.randomUUID(), controller: new AbortController() };
    active.current = request;
    setWorkingId(request.id);
    setProblem("");
    setNotice("");
    setQuestion("");
    setEvents(["Connecting to FleetMind…"]);
    setOverlay([]);
    try {
      await streamReply(id, request.id, text, request.controller.signal, (event) => {
        if (active.current !== request) return;
        showProgress(event);
        if (event.type === "started" || event.type === "final") {
          requestAnimationFrame(() => end.current?.scrollIntoView({ block: "nearest" }));
        }
      });
    } catch (error) {
      if (!request.controller.signal.aborted && active.current === request) {
        setProblem(errorText(error));
        setQuestion(text);
        const result = await cancelRequest(id, request.id).catch(() => null);
        if (active.current === request) setOverlay((previous) => previous.map((message) =>
          message.state === "pending" ? { ...message, state: result?.state ?? "failed" } : message));
      }
    } finally {
      if (active.current === request) {
        active.current = null;
        setWorkingId(null);
        setStopping(false);
        setOverlay((previous) => previous.filter((message) => message.state !== "pending"));
        refreshThread();
      }
    }
  }

  async function stop(requestId: string) {
    if (!id) return;
    setStopping(true);
    setProblem("");
    const local = active.current;
    try {
      const { state } = await cancelRequest(id, requestId);
      if (!mounted.current) return;
      if (state === "cancelled" && local?.id === requestId && active.current === local) {
        active.current = null;
        local.controller.abort();
        setOverlay((previous) => previous.map((message) => message.state === "pending"
          ? { ...message, state: "cancelled" } : message));
        setEvents((previous) => [...previous, "Request stopped"]);
        setWorkingId(null);
      }
      refreshThread();
    } catch (error) {
      if (mounted.current) {
        setProblem(errorText(error));
        if (local?.id === requestId) local.controller.abort();
      }
    } finally { if (mounted.current) setStopping(false); }
  }

  async function update(changes: Partial<Scope & Pick<Conversation, "title" | "archived">>) {
    if (!path) return;
    setBusy(true);
    setProblem("");
    try {
      const updated = await fleetMindRequest<Conversation>(path, writeJson("PATCH", changes));
      if (mounted.current) {
        onChange(updated);
        if (renaming) closeRename();
      }
    } catch (error) { if (mounted.current) setProblem(errorText(error)); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function remove() {
    if (!conversation || !path || !window.confirm(`Permanently delete “${conversation.title}” and its messages?`)) return;
    setBusy(true);
    try {
      await fleetMindRequest<void>(`${path}?confirm=${conversation.id}`, { method: "DELETE" });
      if (mounted.current) onDelete();
    } catch (error) { if (mounted.current) setProblem(errorText(error)); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function loadOlder() {
    if (!path || !olderCursor) return;
    setBusy(true);
    try {
      const page = await fleetMindRequest<MessagePage>(`${path}/messages?before_id=${olderCursor}`);
      if (mounted.current) setOlder({ items: [...page.items, ...(older?.items ?? [])], next_before_id: page.next_before_id });
    } catch (error) { if (mounted.current) setProblem(errorText(error)); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (conversation) {
      await send(question);
    } else {
      setBusy(true);
      setProblem("");
      try { await onCreate(scope); }
      catch (error) { if (mounted.current) setProblem(errorText(error)); }
      finally { if (mounted.current) setBusy(false); }
    }
  }

  function suggest(value: string) {
    setQuestion(value);
    requestAnimationFrame(() => composer.current?.focus());
  }

  const canCompose = Boolean(conversation && !conversation.archived && canSend && !locked);
  return <section className="copilot-thread" aria-label="Conversation workspace">
    <header className="copilot-thread-header">
      <div>
        <h2>{conversation?.title ?? "New investigation"}</h2>
        {conversation?.archived && <span className="copilot-muted">Archived conversation</span>}
      </div>
      {conversation && <div className="copilot-thread-actions">
        <button type="button" className="copilot-icon-button" aria-label="Rename conversation" title="Rename"
          ref={renameButton} disabled={locked} onClick={() => { setTitle(conversation.title); setRenaming(true); }}><Pencil size={17} /></button>
        <button type="button" className="copilot-icon-button" disabled={locked}
          aria-label={conversation.archived ? "Restore conversation" : "Archive conversation"}
          title={conversation.archived ? "Restore" : "Archive"}
          onClick={() => void update({ archived: !conversation.archived })}>
          {conversation.archived ? <RotateCcw size={17} /> : <Archive size={17} />}
        </button>
        <button type="button" className="copilot-icon-button copilot-danger" aria-label="Delete conversation"
          title="Delete" disabled={locked} onClick={() => void remove()}><Trash2 size={17} /></button>
      </div>}
    </header>
    {renaming && <form className="copilot-rename" onSubmit={(event) => {
      event.preventDefault();
      if (title.trim()) void update({ title });
    }}>
      <label>Conversation title <input value={title} onChange={(event) => setTitle(event.target.value)}
        maxLength={120} required autoFocus onKeyDown={(event) => { if (event.key === "Escape") closeRename(); }} /></label>
      <button type="submit" className="copilot-button" disabled={!title.trim() || locked}>Save title</button>
      <button type="button" className="copilot-text-button" onClick={closeRename}>Cancel</button>
    </form>}
    <ContextControls scope={scope} disabled={locked} onScope={(next) => {
      if (conversation) void update(next);
      else setDraftScope(next);
    }} />
    <div className="copilot-log">
      <span className="copilot-sr-only" role="status">{notice}</span>
      {thread.error && <p className="copilot-error" role="alert">{thread.error}
        <button type="button" className="copilot-text-button" onClick={refreshThread}>Reload messages</button>
      </p>}
      {olderCursor && <button type="button" className="copilot-button copilot-older" disabled={busy}
        onClick={() => void loadOlder()}><History size={16} /> Load earlier messages</button>}
      {id && thread.pending && !messages.length && <p role="status" className="copilot-muted">Loading messages…</p>}
      {!messages.length && !thread.pending && !thread.error && <div className="copilot-empty">
        <div className="copilot-empty-icon"><Sparkles size={28} aria-hidden="true" /></div>
        <h3>{conversation ? "What would you like to investigate?" : "Review the evidence behind an alert"}</h3>
        {!conversation && <p>Start a conversation to inspect recorded predictions, asset history, and maintenance guidance.</p>}
        {conversation && !conversation.archived && <div className="copilot-suggestions">
          {suggestions.map((item) => <button type="button" key={item} onClick={() => suggest(item)} disabled={!canCompose}>
            {item}<ArrowRight size={16} aria-hidden="true" />
          </button>)}
        </div>}
      </div>}
      {messages.map((message) => <article key={message.id} className={`copilot-message copilot-message-${message.role}`}
        aria-label={message.role === "user" ? "Your question" : "FleetMind response"}>
        <div className="copilot-message-meta">
          {message.role === "assistant" && <Sparkles size={16} aria-hidden="true" />}
          <strong>{message.role === "user" ? "You" : "FleetMind"}</strong>
          <time dateTime={message.created_at}>{timestampLabel(message.created_at)}</time>
        </div>
        {message.role === "assistant" ? <CopilotEvidence message={message} onInspect={setSource} />
          : <>
            <p className="copilot-user-text">{message.content}</p>
            {(message.asset_id || message.prediction_id) && <small className="copilot-muted">
              {[message.asset_id, message.prediction_id && predictionLabel(message.prediction_id)].filter(Boolean).join(" · ")}
            </small>}
            {(message.state === "failed" || message.state === "cancelled") && <div className="copilot-message-retry">
              <span>{message.state === "failed" ? "Request interrupted" : "Request stopped"}</span>
              <button type="button" className="copilot-text-button" disabled={!canCompose}
                onClick={() => suggest(message.content)}><RotateCcw size={14} /> Retry question</button>
            </div>}
          </>}
        {message.response?.status === "unavailable" && <button type="button" className="copilot-text-button" disabled={!canCompose}
          onClick={() => suggest(messages.find((entry) => entry.role === "user" && entry.request_id === message.request_id)?.content ?? "")}>
          <RotateCcw size={14} /> Retry question</button>}
      </article>)}
      <Progress events={working ? events : events.at(-1)?.includes("stopped") ? events.slice(-1) : []} />
      <div ref={end} />
    </div>
    {problem && <p className="copilot-error copilot-thread-error" role="alert"><CircleAlert size={16} />{problem}</p>}
    <form className="copilot-composer" onSubmit={(event) => void submit(event)}>
      {conversation ? <>
        <label className="copilot-sr-only" htmlFor="copilot-question">Ask FleetMind</label>
        <textarea id="copilot-question" ref={composer} placeholder={conversation.archived ? "Restore to continue the investigation" : "Ask about an alert, sensor reading, or model result…"}
          value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={QUESTION_LIMIT}
          rows={2} disabled={!canCompose} onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }} />
        <div className="copilot-composer-footer">
          <span><ShieldCheck size={14} aria-hidden="true" /> Human review required</span>
          {working || pending ? <button type="button" className="copilot-button" disabled={stopping || !stoppableId}
            onClick={() => { if (stoppableId) void stop(stoppableId); }}><Square size={14} />{stopping ? "Stopping…" : "Stop"}</button>
            : <button type="submit" className="copilot-primary" disabled={!canCompose || !question.trim()}><ArrowUp size={16} /> Send</button>}
        </div>
      </> : <button className="copilot-primary" type="submit" disabled={busy}>
        {busy ? <Loader2 size={17} className="spinning" /> : <Plus size={17} />} Start conversation
      </button>}
    </form>
    {source && <SourceDrawer citation={source} onClose={() => setSource(null)} />}
  </section>;
}

function readScope(params: ReturnType<typeof useSearchParams>): Scope {
  const asset = params.get("asset");
  const prediction = params.get("prediction");
  return {
    asset_id: asset && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(asset) ? asset : null,
    prediction_id: prediction && /^[1-9][0-9]{0,9}$/.test(prediction) && Number(prediction) <= 2147483647
      ? Number(prediction) : null,
  };
}

export function CopilotWorkspace() {
  const params = useSearchParams();
  const fromUrl = params.get("conversation");
  const selected = fromUrl && UUID_PATTERN.test(fromUrl) ? fromUrl : null;
  const [draftScope, setDraftScope] = useState(() => readScope(params));
  const [expanded, setExpanded] = useState(false);
  const [revision, setRevision] = useState(0);
  const [readinessRevision, setReadinessRevision] = useState(0);
  const [updated, setUpdated] = useState<Conversation | null>(null);
  const creating = useRef<Promise<Conversation> | null>(null);
  const [problem, setProblem] = useState("");
  const provider = useFleetMindQuery<ProviderStatus>("copilot/status", { pollMs: 3000, revision: readinessRevision });
  const knowledge = useFleetMindQuery<KnowledgeStatus>("knowledge/status", { pollMs: 30000, revision: readinessRevision });
  const detail = useFleetMindQuery<Conversation>(selected ? `${CONVERSATIONS}/${selected}` : null, { revision });
  const conversation = updated?.id === selected && !detail.error &&
    (!detail.data || updated.updated_at > detail.data.updated_at) ? updated : detail.data;
  const workspaceHeading = useRef<HTMLHeadingElement>(null);

  function select(id: string | null) {
    setExpanded(false);
    setProblem("");
    const query = new URLSearchParams();
    if (id) query.set("conversation", id);
    window.history.pushState(null, "", query.size ? `/copilot?${query}` : "/copilot");
    workspaceHeading.current?.focus({ preventScroll: true });
  }

  function refresh() { setRevision((count) => count + 1); }

  function create(scope: Scope) {
    if (creating.current) return creating.current;
    creating.current = fleetMindRequest<Conversation>(CONVERSATIONS, writeJson("POST", scope))
      .then((result) => {
        setUpdated(result);
        select(result.id);
        refresh();
        return result;
      }).finally(() => { creating.current = null; });
    return creating.current;
  }

  return <main className="copilot-shell">
    <header className="copilot-topbar">
      <Link className="brand" href="/" aria-label="FleetMind dashboard">
        <span className="brand-symbol"><Zap size={20} aria-hidden="true" /></span>
        <strong>FleetMind<span className="brand-dot">.</span></strong>
      </Link>
      <nav aria-label="FleetMind">
        <Link href="/"><ArrowLeft size={16} aria-hidden="true" /><span>Command center</span></Link>
        <Link href="/assets"><Factory size={16} aria-hidden="true" /><span>Assets</span></Link>
        <Link href="/model-intelligence"><Activity size={16} aria-hidden="true" /><span>Model</span></Link>
      </nav>
    </header>
    <div className="copilot-container">
      <div className="copilot-heading">
        <h1 ref={workspaceHeading} tabIndex={-1}>Maintenance <span>Copilot</span></h1>
        <Readiness provider={provider.data} knowledge={knowledge.data} error={provider.error}
          onRetry={() => setReadinessRevision((count) => count + 1)} />
      </div>
      {problem && <p className="copilot-error" role="alert">{problem}</p>}
      <div className="copilot-grid">
        <ConversationList selected={selected} revision={revision} onSelect={select} onError={setProblem}
          expanded={expanded} onToggle={() => setExpanded(!expanded)} onNew={() => {
            if (selected) {
              setDraftScope(EMPTY_SCOPE);
              select(null);
            } else {
              void create(draftScope).catch((error) => setProblem(errorText(error)));
            }
          }} />
        {selected && !conversation ? <section className="copilot-thread copilot-loading" aria-label="Conversation">
          {detail.error ? <p role="alert" className="copilot-error">{detail.error}
            <button type="button" className="copilot-text-button" onClick={() => select(null)}>Open a new investigation</button>
          </p> : <p role="status">Loading conversation…</p>}
        </section> : <ConversationThread key={selected ?? "new"} conversation={conversation}
          scope={conversation ?? draftScope} setDraftScope={setDraftScope} canSend={provider.data?.configured === true}
          onCreate={create} onChange={(item) => { setUpdated(item); refresh(); }}
          onDelete={() => { select(null); setDraftScope(EMPTY_SCOPE); refresh(); }} onHistoryChange={refresh} />}
      </div>
    </div>
  </main>;
}
