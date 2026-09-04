// ============================================================
// App.tsx – Root application component
// ============================================================

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, FlaskConical, Hash } from "lucide-react";
import { sendMessage } from "./api";
import type { Message, AccountId } from "./types";
import { ACCOUNTS } from "./types";
import ChatMessage from "./components/ChatMessage";
import LoadingSkeleton from "./components/LoadingSkeleton";

// Native browser UUID
function genId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

const SUGGESTIONS = [
  "Cancel order ORD-1001 for me",
  "What is the cancellation policy?",
  "Check ticket TKT-501 status",
  "Was there a pickup delay on my recent order?",
];

export default function App() {
  const [accountId, setAccountId] = useState<AccountId>("ACCT-001");
  const [sessionId] = useState<string>(() => `sess-${genId()}`);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  // Derived: is there an unresolved action card in the feed?
  const hasPendingAction = messages.some(
    (m) => m.staged_action && !m.action_resolved
  );

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const handleSend = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isLoading || hasPendingAction) return;

      const userMsg: Message = {
        id: genId(),
        role: "user",
        text: trimmed,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, userMsg]);
      setInputText("");
      setIsLoading(true);

      try {
        // Build conversation history from prior turns (exclude error messages)
        const history = messages
          .filter((m) => !m.is_error && (m.role === "user" || m.role === "bot"))
          .map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.text }))
          .slice(-10); // last 10 turns max

        const data = await sendMessage(accountId, trimmed, sessionId, history);

        const botMsg: Message = {
          id: genId(),
          role: "bot",
          text: data.reply,
          timestamp: new Date(),
          tool_logs: data.tool_logs,
          staged_action: data.staged_action,
          action_resolved: null,
        };

        setMessages((prev) => [...prev, botMsg]);
      } catch (err) {
        const errMsg: Message = {
          id: genId(),
          role: "bot",
          text: err instanceof Error ? err.message : "Unable to complete request. Please try again.",
          timestamp: new Date(),
          is_error: true,
        };
        setMessages((prev) => [...prev, errMsg]);
      } finally {
        setIsLoading(false);
      }
    },
    [accountId, sessionId, messages, isLoading, hasPendingAction]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(inputText);
    }
  };

  const handleActionResolved = useCallback(
    (messageId: string, resolution: "confirmed" | "rejected") => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, action_resolved: resolution } : m
        )
      );
    },
    []
  );

  const accountName = ACCOUNTS.find((a) => a.id === accountId)?.name ?? accountId;

  return (
    <div className="app-layout">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">✈</div>
          <div>
            <div className="header-title">ParcelPilot AI</div>
            <div className="header-subtitle">Autonomous CS Agent</div>
          </div>
          <div className="header-status">
            <span className="status-dot" />
            <span>Online</span>
          </div>
        </div>

        <div className="assessor-wrapper">
          <span className="assessor-badge">
            <FlaskConical size={11} />
            Assessor Mode
          </span>
          <select
            className="account-select"
            value={accountId}
            onChange={(e) => {
              setAccountId(e.target.value as AccountId);
              setMessages([]); // Reset chat on account switch
            }}
            id="account-selector"
          >
            {ACCOUNTS.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.id})
              </option>
            ))}
          </select>
        </div>

        <div className="session-pill">
          <Hash size={9} />
          {sessionId}
        </div>
      </header>

      {/* ── Chat Feed ──────────────────────────────────────── */}
      <div className="chat-container" ref={feedRef}>
        <div className="chat-feed">
          {messages.length === 0 && !isLoading ? (
            <div className="empty-state">
              <div className="empty-icon">✈️</div>
              <div className="empty-title">ParcelPilot AI Agent</div>
              <div className="empty-hint">
                Acting as <strong style={{ color: "var(--text-accent)", fontWeight: 700 }}>{accountName}</strong>.
                Query orders, tickets, policies, or request actions like cancellations and escalations.
              </div>
              <div className="suggestion-pills">
                {SUGGESTIONS.map((s, i) => (
                  <button
                    key={i}
                    className="suggestion-pill"
                    onClick={() => handleSend(s)}
                    id={`suggestion-${i}`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  sessionId={sessionId}
                  onActionResolved={handleActionResolved}
                />
              ))}
              {isLoading && <LoadingSkeleton />}
            </>
          )}
        </div>
      </div>

      {/* ── Input Bar ──────────────────────────────────────── */}
      <div className="input-bar">
        {hasPendingAction && (
          <div className="input-pending-notice">
            ⚠️ Confirm or reject the pending action above before sending a new message.
          </div>
        )}
        <div className="input-bar-inner">
          <div className={`input-field-wrap${hasPendingAction ? " locked" : ""}`}>
            <textarea
              className="chat-input"
              placeholder={
                hasPendingAction
                  ? "Resolve the pending action first…"
                  : `Message agent as ${accountName}… (Enter to send)`
              }
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading || hasPendingAction}
              rows={1}
              id="chat-input"
            />
          </div>
          <button
            className="send-btn"
            onClick={() => handleSend(inputText)}
            disabled={!inputText.trim() || isLoading || hasPendingAction}
            id="send-button"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
