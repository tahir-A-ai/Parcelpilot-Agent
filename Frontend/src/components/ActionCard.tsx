// ============================================================
// ActionCard – inline human-in-the-loop confirmation card
// rendered directly in the chat feed under a bot message.
// Locks the input while awaiting user decision.
// ============================================================

import { useState } from "react";
import { CheckCircle2, XCircle, AlertTriangle, Loader2 } from "lucide-react";
import type { StagedAction } from "../types";
import { parseActionDetails } from "../types";
import { confirmAction } from "../api";

interface ActionCardProps {
  staged: StagedAction;
  sessionId: string;
  onResolved: (resolution: "confirmed" | "rejected") => void;
}

function actionTypeLabel(type?: string): string {
  if (!type) return "Pending Action";
  const map: Record<string, string> = {
    CANCEL_ORDER: "Cancel Order",
    ISSUE_CREDIT: "Issue Service Credit",
    ESCALATE_TICKET: "Escalate Support Ticket",
  };
  return map[type] ?? type;
}

export default function ActionCard({ staged, sessionId, onResolved }: ActionCardProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const details = parseActionDetails(staged);
  const label = actionTypeLabel(staged.action_type as string | undefined);

  async function handleDecision(confirmed: boolean) {
    if (!staged.action_id) return;
    setLoading(true);
    setError(null);
    try {
      await confirmAction(sessionId, staged.action_id as string, confirmed);
      onResolved(confirmed ? "confirmed" : "rejected");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="action-card">
      {/* Header */}
      <div className="action-card-header">
        <div className="action-card-icon">
          <AlertTriangle size={15} />
          <div className="action-card-pulse" />
        </div>
        <div>
          <div className="action-card-title">{label}</div>
          <div className="action-card-subtitle">Requires your confirmation before executing</div>
        </div>
      </div>

      {/* Details */}
      <div className="action-card-body">
        {details.map((d, i) => (
          <div key={i} className="action-detail-row">
            <span className="action-detail-label">{d.label}</span>
            <span className={`action-detail-value${d.highlight ? " highlight" : ""}`}>
              {d.value}
            </span>
          </div>
        ))}
        {error && (
          <div style={{ color: "var(--accent-red)", fontSize: 12, marginTop: 4 }}>
            {error}
          </div>
        )}
      </div>

      {/* Action Buttons */}
      <div className="action-card-footer">
        <button
          className="btn-confirm"
          onClick={() => handleDecision(true)}
          disabled={loading}
          id={`confirm-${staged.action_id}`}
        >
          {loading ? (
            <Loader2 size={13} className="spin" />
          ) : (
            <CheckCircle2 size={13} />
          )}
          Confirm Action
        </button>
        <button
          className="btn-reject"
          onClick={() => handleDecision(false)}
          disabled={loading}
          id={`reject-${staged.action_id}`}
        >
          <XCircle size={13} />
          Reject
        </button>
      </div>
    </div>
  );
}

// Resolved badge shown after decision
export function ActionResolvedBadge({ resolution }: { resolution: "confirmed" | "rejected" }) {
  return (
    <div className={`action-resolved-badge ${resolution}`}>
      {resolution === "confirmed" ? (
        <><CheckCircle2 size={12} /> Action confirmed & executed</>
      ) : (
        <><XCircle size={12} /> Action rejected</>
      )}
    </div>
  );
}
