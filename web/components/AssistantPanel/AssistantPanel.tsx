"use client";

import Link from "next/link";
import React, { useEffect, useRef, useState } from "react";
import styles from "./AssistantPanel.module.css";

const API = "/api/proxy";

type ClientData = { id: string; name: string };

type MessageData = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system" | string;
  content: string;
  created_at: string;
};

type ConversationSummary = {
  id: string;
  client_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
};

type ConversationData = ConversationSummary & {
  messages: MessageData[];
};

type AssistantState = {
  client: ClientData | null;
  conversations: ConversationSummary[];
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

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function titleForConversation(conv: ConversationSummary | ConversationData | null): string {
  return conv?.title?.trim() || "New conversation";
}

const CONTENT_TYPE_LABELS: Record<string, string> = {
  blog_post: "Blog post",
  faq_page: "FAQ page",
  linkedin_post: "LinkedIn post",
  platform_listing: "Platform listing",
  review_response: "Review response",
  schema_markup: "Schema markup",
  other: "Content draft",
};

function contentTypeLabel(type: string): string {
  return CONTENT_TYPE_LABELS[type] ?? "Content draft";
}

function renderMarkdown(text: string): React.ReactNode[] {
  const blocks = text.split(/\n{2,}/);
  const nodes: React.ReactNode[] = [];

  blocks.forEach((block, bi) => {
    const trimmed = block.trim();
    if (!trimmed) return;

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const tagName = level === 1 ? "h2" : level === 2 ? "h3" : "h4";
      nodes.push(React.createElement(tagName, { key: bi, className: styles.mdHeading }, inlineFormat(headingMatch[2])));
      return;
    }

    const lines = trimmed.split("\n");
    const isList = lines.every(l => /^[-*•]\s/.test(l.trim()) || /^\d+\.\s/.test(l.trim()) || l.trim() === "");
    if (isList && lines.some(l => /^[-*•]\s/.test(l.trim()) || /^\d+\.\s/.test(l.trim()))) {
      nodes.push(
        <ul key={bi} className={styles.mdList}>
          {lines
            .filter(l => l.trim())
            .map((l, li) => (
              <li key={li} className={styles.mdListItem}>
                {inlineFormat(l.replace(/^[-*•]\s+/, "").replace(/^\d+\.\s+/, ""))}
              </li>
            ))}
        </ul>
      );
      return;
    }

    const lineNodes: React.ReactNode[] = [];
    lines.forEach((line, li) => {
      const t = line.trim();
      if (!t) return;
      if (/^[-*•]\s/.test(t) || /^\d+\.\s/.test(t)) {
        lineNodes.push(
          <div key={li} className={styles.mdInlineItem}>
            <span className={styles.mdBullet}>•</span>
            {inlineFormat(t.replace(/^[-*•]\s+/, "").replace(/^\d+\.\s+/, ""))}
          </div>
        );
      } else {
        lineNodes.push(
          <span key={li} className={styles.mdLine}>
            {inlineFormat(t)}{li < lines.length - 1 ? " " : ""}
          </span>
        );
      }
    });
    nodes.push(<p key={bi} className={styles.mdParagraph}>{lineNodes}</p>);
  });

  return nodes.length > 0 ? nodes : [<p key="empty" className={styles.mdParagraph}>{text}</p>];
}

function inlineFormat(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          part
        )
      )}
    </>
  );
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
    conversations: [],
    conversation: null,
    loading: true,
    streaming: false,
    error: null,
  });
  const [messages, setMessages] = useState<MessageData[]>([]);
  const [draft, setDraft] = useState("");
  const [draftNotice, setDraftNotice] = useState<ContentDraftSummary | null>(null);
  const [toolActivity, setToolActivity] = useState<string | null>(null);
  const [editFromMessageId, setEditFromMessageId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const clientsRes = await fetch(`${API}/v1/clients`, { cache: "no-store" });
        if (!clientsRes.ok) throw new Error(await readError(clientsRes, "Unable to load clients"));
        const clients: ClientData[] = await clientsRes.json();
        const client = clients[0] ?? null;
        if (!client) {
          if (active) setState(prev => ({ ...prev, loading: false }));
          return;
        }

        const convListRes = await fetch(
          `${API}/v1/assistant/conversations?client_id=${encodeURIComponent(client.id)}`,
          { cache: "no-store" }
        );
        if (!convListRes.ok) throw new Error(await readError(convListRes, "Unable to load conversations"));
        const convList: ConversationSummary[] = await convListRes.json();

        let conversation: ConversationData;
        let conversations: ConversationSummary[] = convList;

        if (convList.length > 0) {
          const detailRes = await fetch(`${API}/v1/assistant/conversations/${convList[0].id}`, { cache: "no-store" });
          if (!detailRes.ok) throw new Error(await readError(detailRes, "Unable to load conversation"));
          conversation = await detailRes.json();
        } else {
          const createRes = await fetch(`${API}/v1/assistant/conversations`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ client_id: client.id }),
          });
          if (!createRes.ok) throw new Error(await readError(createRes, "Unable to create conversation"));
          conversation = await createRes.json();
          conversations = [conversation];
        }

        if (active) {
          setMessages(conversation.messages ?? []);
          setState({ client, conversations, conversation, loading: false, streaming: false, error: null });
        }
      } catch (error) {
        if (active) {
          setState(prev => ({
            ...prev,
            loading: false,
            error: error instanceof Error ? error.message : "Unable to load assistant",
          }));
        }
      }
    }

    void load();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, state.streaming]);

  // ── Session actions ───────────────────────────────────────────────────────
  async function handleNewChat() {
    if (!state.client || state.streaming) return;
    try {
      const res = await fetch(`${API}/v1/assistant/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: state.client.id }),
      });
      if (!res.ok) throw new Error("Unable to create conversation");
      const conv: ConversationData = await res.json();
      setState(prev => ({
        ...prev,
        conversations: [conv, ...prev.conversations],
        conversation: conv,
        error: null,
      }));
      setMessages([]);
      setDraft("");
      setDraftNotice(null);
      setEditFromMessageId(null);
      setConfirmDeleteId(null);
    } catch {
      setState(prev => ({ ...prev, error: "Unable to create new chat" }));
    }
  }

  async function switchConversation(convId: string) {
    if (convId === state.conversation?.id || state.streaming) return;
    setConfirmDeleteId(null);
    try {
      const res = await fetch(`${API}/v1/assistant/conversations/${convId}`, { cache: "no-store" });
      if (!res.ok) throw new Error("Unable to load conversation");
      const conv: ConversationData = await res.json();
      setState(prev => ({ ...prev, conversation: conv, error: null }));
      setMessages(conv.messages ?? []);
      setDraft("");
      setDraftNotice(null);
      setEditFromMessageId(null);
    } catch {
      setState(prev => ({ ...prev, error: "Unable to switch conversation" }));
    }
  }

  async function deleteConversation(convId: string) {
    await fetch(`${API}/v1/assistant/conversations/${convId}`, { method: "DELETE" });
    setConfirmDeleteId(null);
    const remaining = state.conversations.filter(c => c.id !== convId);

    if (state.conversation?.id === convId) {
      if (remaining.length > 0) {
        setState(prev => ({ ...prev, conversations: remaining }));
        await switchConversation(remaining[0].id);
      } else {
        try {
          const res = await fetch(`${API}/v1/assistant/conversations`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ client_id: state.client!.id }),
          });
          if (!res.ok) throw new Error();
          const conv: ConversationData = await res.json();
          setState(prev => ({ ...prev, conversations: [conv], conversation: conv }));
          setMessages([]);
        } catch {
          setState(prev => ({ ...prev, conversations: [], conversation: null }));
        }
      }
    } else {
      setState(prev => ({ ...prev, conversations: remaining }));
    }
  }

  async function clearChat() {
    if (!state.conversation || messages.length === 0) return;
    const convId = state.conversation.id;
    await fetch(`${API}/v1/assistant/conversations/${convId}/messages`, { method: "DELETE" });
    setMessages([]);
    setDraftNotice(null);
    setEditFromMessageId(null);
    setState(prev => ({
      ...prev,
      conversations: prev.conversations.map(c =>
        c.id === convId ? { ...c, title: "New conversation" } : c
      ),
      conversation: prev.conversation
        ? { ...prev.conversation, title: "New conversation", messages: [] }
        : null,
    }));
  }

  // ── Streaming controls ────────────────────────────────────────────────────
  function handleStop() {
    abortRef.current?.abort();
  }

  function handleEditMessage(msg: MessageData) {
    setDraft(msg.content);
    setEditFromMessageId(msg.id);
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  // ── Submit / stream ───────────────────────────────────────────────────────
  async function handleSubmit() {
    const content = draft.trim();
    if (!content || !state.conversation || state.streaming) return;

    const conversationId = state.conversation.id;

    // Capture edit index before any state changes
    const editIdx = editFromMessageId ? messages.findIndex(m => m.id === editFromMessageId) : -1;

    if (editFromMessageId) {
      await fetch(
        `${API}/v1/assistant/conversations/${conversationId}/messages/from/${editFromMessageId}`,
        { method: "DELETE" }
      );
      setEditFromMessageId(null);
    }

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
    setToolActivity(null);
    setMessages(prev => {
      const base = editIdx >= 0 ? prev.slice(0, editIdx) : prev;
      return [...base, userMessage, assistantMessage];
    });
    setState(prev => ({ ...prev, streaming: true, error: null }));

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(
        `${API}/v1/assistant/conversations/${conversationId}/messages/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        }
      );
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
          const data = parsed.data as {
            delta?: string;
            message?: MessageData;
            content_draft?: ContentDraftSummary | null;
            tool?: string;
            label?: string;
            status?: string;
          };

          if (parsed.event === "tool_activity" && data.label) {
            setToolActivity(data.label);
          }
          if (parsed.event === "message" && data.delta) {
            setToolActivity(null);
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMessageId
                  ? { ...m, content: `${m.content}${data.delta}` }
                  : m
              )
            );
          }
          if (parsed.event === "done" && data.message) {
            setToolActivity(null);
            setMessages(prev =>
              prev.map(m => (m.id === assistantMessageId ? data.message! : m))
            );
            if (data.content_draft) setDraftNotice(data.content_draft);
            setState(prev => ({
              ...prev,
              conversations: prev.conversations.map(c =>
                c.id === conversationId ? { ...c, updated_at: nowIso() } : c
              ),
            }));
          }
        }
      }
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMessageId && !m.content
              ? { ...m, content: "[Response stopped]" }
              : m
          )
        );
      } else {
        setState(prev => ({
          ...prev,
          error: error instanceof Error ? error.message : "Assistant response failed",
        }));
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMessageId
              ? { ...m, content: "I could not complete that response. Please try again." }
              : m
          )
        );
      }
    } finally {
      setToolActivity(null);
      setState(prev => ({ ...prev, streaming: false }));
      abortRef.current = null;
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div>
          <h1 className={styles.topTitle}>Assistant</h1>
          <p className={styles.topCrumb}>
            {state.client ? state.client.name : "Ask AISO what to do next"}
          </p>
        </div>
        <div className={styles.topActions}>
          <Link href="/dashboard/assistant/drafts" className={styles.secondaryButton}>
            Content library
          </Link>
          <Link href="/dashboard/actions" className={styles.secondaryButton}>
            Action plan
          </Link>
        </div>
      </header>

      <div className={styles.pageBody}>
        {/* ── Sidebar ── */}
        {state.client && (
          <aside className={styles.sidebar}>
            <div className={styles.sidebarHeader}>
              <button
                className={styles.newChatBtn}
                onClick={() => void handleNewChat()}
                disabled={state.streaming}
              >
                <span className={styles.newChatIcon}>+</span>
                New chat
              </button>
            </div>

            <div className={styles.convList}>
              {state.conversations.map(conv => (
                <div
                  key={conv.id}
                  className={`${styles.convItem} ${conv.id === state.conversation?.id ? styles.convItemActive : ""}`}
                >
                  <button
                    className={styles.convItemBtn}
                    onClick={() => void switchConversation(conv.id)}
                    disabled={state.streaming}
                    title={titleForConversation(conv)}
                  >
                    <span className={styles.convItemTitle}>{titleForConversation(conv)}</span>
                    <span className={styles.convItemTime}>{relativeTime(conv.updated_at)}</span>
                  </button>

                  {confirmDeleteId === conv.id ? (
                    <div className={styles.convDeleteConfirm}>
                      <button
                        className={styles.convDeleteYes}
                        onClick={() => void deleteConversation(conv.id)}
                      >
                        Delete
                      </button>
                      <button
                        className={styles.convDeleteCancel}
                        onClick={() => setConfirmDeleteId(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      className={styles.convDeleteBtn}
                      onClick={() => setConfirmDeleteId(conv.id)}
                      title="Delete conversation"
                      aria-label="Delete conversation"
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}

              {state.conversations.length === 0 && !state.loading && (
                <p className={styles.convEmpty}>No conversations yet</p>
              )}
            </div>
          </aside>
        )}

        {/* ── Main area ── */}
        <main className={styles.mainColumn}>
          <div className={styles.content}>
            <section className={styles.hero}>
              <div>
                <h1>Your AI visibility co-pilot</h1>
                <p>
                  Ask about your scan results, request content to fix visibility gaps,
                  or ask what to prioritize next. Drafts stay in the Content Library until you approve them.
                </p>
              </div>
              {state.client && <span className={styles.clientPill}>{state.client.name}</span>}
            </section>

            {state.error && <div className={styles.notice}>{state.error}</div>}

            {draftNotice && (
              <div className={styles.draftNotice}>
                <div className={styles.draftNoticeMeta}>
                  <span className={styles.draftNoticeType}>{contentTypeLabel(draftNotice.content_type)}</span>
                  <strong className={styles.draftNoticeTitle}>{draftNotice.title}</strong>
                  <span className={styles.draftNoticeStatus}>Saved · pending review</span>
                </div>
                <div className={styles.draftNoticeActions}>
                  <a
                    href={`${API}/v1/assistant/content-drafts/${draftNotice.id}/export?format=pdf`}
                    className={styles.exportButton}
                    target="_blank"
                    rel="noopener noreferrer"
                    download
                  >
                    PDF
                  </a>
                  <a
                    href={`${API}/v1/assistant/content-drafts/${draftNotice.id}/export?format=docx`}
                    className={styles.exportButton}
                    target="_blank"
                    rel="noopener noreferrer"
                    download
                  >
                    DOCX
                  </a>
                  <Link href="/dashboard/assistant/drafts" className={styles.draftNoticeLink}>
                    Open Content Library
                  </Link>
                </div>
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
                {/* Chat header */}
                <div className={styles.chatHeader}>
                  <span className={styles.chatHeaderTitle}>
                    {titleForConversation(state.conversation)}
                  </span>
                  <button
                    className={styles.clearChatBtn}
                    onClick={() => void clearChat()}
                    disabled={state.streaming || messages.length === 0}
                    title="Clear all messages"
                  >
                    Clear chat
                  </button>
                </div>

                {/* Messages */}
                <div className={styles.messageList}>
                  {messages.length === 0 && (
                    <div className={styles.welcome}>
                      <h2>How can I help you today?</h2>
                      <div className={styles.welcomePrompts}>
                        {[
                          "What are my top visibility gaps right now?",
                          "Write a LinkedIn post to improve my AI presence",
                          "Which AI providers mention me least?",
                          "Draft a blog post to address my biggest gap",
                        ].map(prompt => (
                          <button
                            key={prompt}
                            type="button"
                            className={styles.promptChip}
                            onClick={() => setDraft(prompt)}
                          >
                            {prompt}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {messages.map(message => (
                    <article
                      key={message.id}
                      className={`${styles.message} ${
                        message.role === "user" ? styles.userMessage : styles.assistantMessage
                      }`}
                    >
                      <div className={styles.messageMeta}>
                        <strong>{message.role === "user" ? "You" : "AISO Assistant"}</strong>
                        <div className={styles.messageMetaRight}>
                          {message.role === "user" && !state.streaming && message.content && (
                            <button
                              className={styles.editMsgBtn}
                              onClick={() => handleEditMessage(message)}
                              title="Edit and resend"
                              aria-label="Edit message"
                            >
                              ✎
                            </button>
                          )}
                          <span>{formatTime(message.created_at)}</span>
                        </div>
                      </div>

                      {message.content ? (
                        message.role === "assistant" ? (
                          <div className={styles.mdContent}>
                            {renderMarkdown(message.content)}
                          </div>
                        ) : (
                          <p className={styles.messageContent}>{message.content}</p>
                        )
                      ) : state.streaming ? (
                        <p className={styles.thinkingLabel}>
                          <span className={styles.thinkingDot} />
                          {toolActivity ?? "Thinking..."}
                        </p>
                      ) : null}
                    </article>
                  ))}

                  <div ref={messagesEndRef} />
                </div>

                {/* Composer */}
                <form className={styles.composer} onSubmit={e => { e.preventDefault(); void handleSubmit(); }}>
                  {editFromMessageId && (
                    <div className={styles.editBanner}>
                      <span>Editing message — submit to replace and resend from this point</span>
                      <button
                        type="button"
                        className={styles.editCancelBtn}
                        onClick={() => { setEditFromMessageId(null); setDraft(""); }}
                      >
                        Cancel edit
                      </button>
                    </div>
                  )}
                  <textarea
                    ref={textareaRef}
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        if (draft.trim() && !state.streaming) {
                          e.currentTarget.form?.requestSubmit();
                        }
                      }
                    }}
                    placeholder="Ask about scan results, open actions, content drafts, or what to prioritize next..."
                    rows={3}
                    maxLength={4000}
                    disabled={state.streaming}
                    className={editFromMessageId ? styles.textareaEditing : ""}
                  />
                  <div className={styles.composerFooter}>
                    <span className={styles.contextLabel}>
                      {state.streaming
                        ? (toolActivity ?? "Thinking...")
                        : editFromMessageId
                        ? "Editing — press Enter or Send to resend"
                        : "Enter to send · Shift+Enter for new line"}
                    </span>
                    <div className={styles.composerActions}>
                      {state.streaming ? (
                        <button
                          type="button"
                          className={styles.stopButton}
                          onClick={handleStop}
                        >
                          Stop
                        </button>
                      ) : (
                        <button type="submit" disabled={!draft.trim()}>
                          {editFromMessageId ? "Resend" : "Send"}
                        </button>
                      )}
                    </div>
                  </div>
                </form>
              </section>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
