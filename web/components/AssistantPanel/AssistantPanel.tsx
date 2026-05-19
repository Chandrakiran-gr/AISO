"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import styles from "./AssistantPanel.module.css";

const API = "/api/proxy";

type ClientData = {
  id: string;
  name: string;
};

type MessageData = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system" | string;
  content: string;
  created_at: string;
};

type ConversationData = {
  id: string;
  client_id: string;
  title: string | null;
  messages: MessageData[];
};

type AssistantState = {
  client: ClientData | null;
  conversation: ConversationData | null;
  loading: boolean;
  streaming: boolean;
  error: string | null;
};

type ContentDraftSummary = {
  id: string;
  title: string;
  status: string;
  content_type: string;
};

function nowIso() {
  return new Date().toISOString();
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

function titleForConversation(conversation: ConversationData | null): string {
  return conversation?.title?.trim() || "Assistant conversation";
}

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    // Keep fallback.
  }
  return fallback;
}

async function loadConversation(clientId: string): Promise<ConversationData> {
  const listRes = await fetch(`${API}/v1/assistant/conversations?client_id=${encodeURIComponent(clientId)}`, {
    cache: "no-store",
  });
  if (!listRes.ok) throw new Error(await readError(listRes, "Unable to load assistant conversations"));
  const conversations: ConversationData[] = await listRes.json();
  const latest = conversations[0] ?? null;
  if (latest) {
    const detailRes = await fetch(`${API}/v1/assistant/conversations/${latest.id}`, { cache: "no-store" });
    if (!detailRes.ok) throw new Error(await readError(detailRes, "Unable to load assistant history"));
    return detailRes.json();
  }

  const createRes = await fetch(`${API}/v1/assistant/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId }),
  });
  if (!createRes.ok) throw new Error(await readError(createRes, "Unable to create assistant conversation"));
  return createRes.json();
}

function parseSseEvent(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice("event:".length).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

export default function AssistantPanel() {
  const [state, setState] = useState<AssistantState>({
    client: null,
    conversation: null,
    loading: true,
    streaming: false,
    error: null,
  });
  const [messages, setMessages] = useState<MessageData[]>([]);
  const [draft, setDraft] = useState("");
  const [draftNotice, setDraftNotice] = useState<ContentDraftSummary | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error(await readError(clientsRes, "Unable to load clients"));
        const clients: ClientData[] = await clientsRes.json();
        const client = clients[0] ?? null;
        if (!client) {
          if (active) setState((prev) => ({ ...prev, loading: false }));
          return;
        }

        const conversation = await loadConversation(client.id);
        if (active) {
          setMessages(conversation.messages ?? []);
          setState({
            client,
            conversation,
            loading: false,
            streaming: false,
            error: null,
          });
        }
      } catch (error) {
        if (active) {
          setState((prev) => ({
            ...prev,
            loading: false,
            error: error instanceof Error ? error.message : "Unable to load assistant",
          }));
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, state.streaming]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || !state.conversation || state.streaming) return;

    const conversationId = state.conversation.id;
    const userMessage: MessageData = {
      id: `local-user-${Date.now()}`,
      conversation_id: conversationId,
      role: "user",
      content,
      created_at: nowIso(),
    };
    const assistantMessageId = `local-assistant-${Date.now()}`;
    const assistantMessage: MessageData = {
      id: assistantMessageId,
      conversation_id: conversationId,
      role: "assistant",
      content: "",
      created_at: nowIso(),
    };

    setDraft("");
    setDraftNotice(null);
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setState((prev) => ({ ...prev, streaming: true, error: null }));

    try {
      const response = await fetch(`${API}/v1/assistant/conversations/${conversationId}/messages/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!response.ok || !response.body) {
        throw new Error(await readError(response, "Assistant response failed"));
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;

      while (!done) {
        const result = await reader.read();
        done = result.done;
        buffer += decoder.decode(result.value ?? new Uint8Array(), { stream: !done });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          const parsed = parseSseEvent(block);
          if (!parsed) continue;
          const data = parsed.data as { delta?: string; message?: MessageData; content_draft?: ContentDraftSummary | null };
          if (parsed.event === "message" && data.delta) {
            setMessages((prev) =>
              prev.map((message) =>
                message.id === assistantMessageId
                  ? { ...message, content: `${message.content}${data.delta}` }
                  : message,
              ),
            );
          }
          if (parsed.event === "done" && data.message) {
            setMessages((prev) =>
              prev.map((message) => (message.id === assistantMessageId ? data.message! : message)),
            );
            if (data.content_draft) setDraftNotice(data.content_draft);
          }
        }
      }
    } catch (error) {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : "Assistant response failed",
      }));
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantMessageId
            ? { ...message, content: "I could not complete that response. Please try again." }
            : message,
        ),
      );
    } finally {
      setState((prev) => ({ ...prev, streaming: false }));
    }
  }

  const openPrompt = "What are my top action items?";

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Assistant</h1>
          <p className={styles.topCrumb}>
            {state.client
              ? `${state.client.name} · ${titleForConversation(state.conversation)}`
              : "Ask AISO what to do next"}
          </p>
        </div>
        <div className={styles.topActions}>
          <Link href="/dashboard/assistant/drafts" className={styles.secondaryButton}>
            Content library
          </Link>
          <Link href="/dashboard/actions" className={styles.secondaryButton}>
            View action plan
          </Link>
        </div>
      </header>

      <main className={styles.content}>
        <section className={styles.hero}>
          <div>
            <h1>Ask what to do next</h1>
            <p>
              The assistant uses your active business profile, latest scan summary, and open action items.
            </p>
          </div>
          {state.client && <span className={styles.clientPill}>{state.client.name}</span>}
        </section>

        {state.error && <div className={styles.notice}>{state.error}</div>}
        {draftNotice && (
          <div className={styles.notice}>
            Draft saved: {draftNotice.title}.{" "}
            <Link href="/dashboard/assistant/drafts">Open Content Library</Link>
          </div>
        )}
        {state.loading && <div className={styles.notice}>Loading assistant...</div>}

        {!state.loading && !state.client && (
          <section className={styles.emptyState}>
            <h2>No business profile yet</h2>
            <p>Create a business profile and run a scan before using the assistant.</p>
            <Link href="/onboarding" className={styles.primaryButton}>
              Start onboarding
            </Link>
          </section>
        )}

        {!state.loading && state.client && (
          <section className={styles.chatShell} aria-label="AISO assistant chat">
            <div className={styles.messageList}>
              {messages.length === 0 && (
                <div className={styles.welcome}>
                  <h2>Start with a practical next-step question.</h2>
                  <button type="button" onClick={() => setDraft(openPrompt)}>
                    {openPrompt}
                  </button>
                </div>
              )}

              {messages.map((message) => (
                <article
                  key={message.id}
                  className={`${styles.message} ${
                    message.role === "user" ? styles.userMessage : styles.assistantMessage
                  }`}
                >
                  <div className={styles.messageMeta}>
                    <strong>{message.role === "user" ? "You" : "AISO Assistant"}</strong>
                    <span>{formatTime(message.created_at)}</span>
                  </div>
                  <p>{message.content || (state.streaming ? "Thinking..." : "")}</p>
                </article>
              ))}
              <div ref={messagesEndRef} />
            </div>

            <form className={styles.composer} onSubmit={(event) => void handleSubmit(event)}>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask about scan results, open actions, content drafts, or what to prioritize next..."
                rows={3}
                maxLength={4000}
                disabled={state.streaming}
              />
              <div className={styles.composerFooter}>
                <span>{state.streaming ? "Streaming response..." : "Context: active client, latest scan, open actions"}</span>
                <button type="submit" disabled={!draft.trim() || state.streaming}>
                  Send
                </button>
              </div>
            </form>
          </section>
        )}
      </main>
    </div>
  );
}
