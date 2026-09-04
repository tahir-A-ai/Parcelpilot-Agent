// ============================================================
// ChatMessage – renders a single chat message with avatars,
// tool badges, Markdown formatting, and optional inline action card.
// ============================================================

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertCircle } from "lucide-react";
import type { Message } from "../types";
import ToolBadges from "./ToolBadges";
import ActionCard, { ActionResolvedBadge } from "./ActionCard";

interface ChatMessageProps {
  message: Message;
  sessionId: string;
  onActionResolved: (messageId: string, resolution: "confirmed" | "rejected") => void;
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function ChatMessage({ message, sessionId, onActionResolved }: ChatMessageProps) {
  const isUser = message.role === "user";
  const isError = message.is_error;

  return (
    <div className={`message-wrapper ${message.role}${isError ? " is-error" : ""}`}>
      <div className={`avatar ${message.role}${isError ? " error" : ""}`}>
        {isUser ? "👤" : isError ? "⚠️" : "🤖"}
      </div>

      <div className="message-content">
        {/* Tool badges before the bot bubble */}
        {!isUser && !isError && message.tool_logs && message.tool_logs.length > 0 && (
          <ToolBadges logs={message.tool_logs} />
        )}

        {/* Main message bubble */}
        {isError ? (
          <div className="message-bubble error-bubble">
            <div className="error-bubble-header">
              <AlertCircle size={15} color="#fb7185" />
              <span>Service Notice</span>
            </div>
            <div className="error-bubble-text">{message.text}</div>
          </div>
        ) : (
          <div className="message-bubble markdown-body">
            {isUser ? (
              message.text
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.text}
              </ReactMarkdown>
            )}
          </div>
        )}

        {/* Inline Action Card */}
        {!isUser && message.staged_action && !message.action_resolved && (
          <ActionCard
            staged={message.staged_action}
            sessionId={sessionId}
            onResolved={(res) => onActionResolved(message.id, res)}
          />
        )}

        {/* Resolved badge */}
        {!isUser && message.action_resolved && (
          <ActionResolvedBadge resolution={message.action_resolved} />
        )}

        <div className="message-time">{formatTime(message.timestamp)}</div>
      </div>
    </div>
  );
}
