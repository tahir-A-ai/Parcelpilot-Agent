// ============================================================
// LoadingSkeleton – shown while the agent is thinking/running
// ============================================================

// ============================================================
// LoadingSkeleton – premium typing indicator while agent thinks
// ============================================================

export default function LoadingSkeleton() {
  return (
    <div className="skeleton-wrapper message-wrapper bot">
      <div className="avatar bot">✈</div>
      <div className="message-content">
        <div className="skeleton-bubble">
          <div className="skeleton-step">
            <div className="typing-dots">
              <div className="typing-dot" />
              <div className="typing-dot" />
              <div className="typing-dot" />
            </div>
            <span>Agent is thinking…</span>
          </div>
          <div className="skeleton-text-line" style={{ width: "75%" }} />
          <div className="skeleton-text-line" style={{ width: "55%" }} />
          <div className="skeleton-text-line" style={{ width: "85%" }} />
        </div>
      </div>
    </div>
  );
}

