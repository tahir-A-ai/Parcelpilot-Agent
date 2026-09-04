// ============================================================
// Shared types for the chat UI
// ============================================================

import type { ToolLog, StagedAction } from "./api";

export type { ToolLog, StagedAction };

export type MessageRole = "user" | "bot";

export interface Message {
  id: string;
  role: MessageRole;
  text: string;
  timestamp: Date;
  is_error?: boolean;
  tool_logs?: ToolLog[];
  staged_action?: StagedAction | null;
  /** Whether the pending action on this message has been resolved */
  action_resolved?: "confirmed" | "rejected" | null;
}

export const ACCOUNTS = [
  { id: "ACCT-001", name: "Northstar Logistics" },
  { id: "ACCT-002", name: "LumenWorks" },
  { id: "ACCT-003", name: "Beacon Retail" },
  { id: "ACCT-004", name: "Apex Freight" },
] as const;

export type AccountId = (typeof ACCOUNTS)[number]["id"];

/** Map tool_name to display label + variant */
export function getToolBadgeProps(toolName: string): {
  label: string;
  variant: "db" | "search" | "action";
  icon: string;
} {
  const lower = toolName.toLowerCase();
  if (lower.includes("query") || lower.includes("structured_data")) {
    return { label: "Database Lookup", variant: "db", icon: "db" };
  }
  if (lower.includes("search") || lower.includes("document")) {
    return { label: "Policy Search", variant: "search", icon: "search" };
  }
  if (lower.includes("stage") || lower.includes("action")) {
    return { label: "Action Prepared", variant: "action", icon: "action" };
  }
  if (lower.includes("python") || lower.includes("interpreter") || lower.includes("code")) {
    return { label: "Policy & Data Analysis", variant: "search", icon: "search" };
  }
  return { label: "Analysis", variant: "db", icon: "db" };
}

/** Flatten staged action payload for display */
export function parseActionDetails(staged: StagedAction): Array<{ label: string; value: string; highlight?: boolean }> {
  const details: Array<{ label: string; value: string; highlight?: boolean }> = [];

  const id = staged.action_id;
  if (id) details.push({ label: "Action ID", value: id });

  const type = staged.action_type || (staged as Record<string, unknown>).type as string;
  if (type) details.push({ label: "Type", value: String(type) });

  const summary = staged.summary;
  if (summary) details.push({ label: "Summary", value: String(summary) });

  // Try to parse payload if it's a string
  let payload = staged.payload;
  if (!payload && staged.observations) {
    try {
      payload = JSON.parse(String(staged.observations));
    } catch { /* ignore */ }
  }

  if (payload && typeof payload === "object") {
    const p = payload as Record<string, unknown>;
    if (p.order_id) details.push({ label: "Order", value: String(p.order_id) });
    if (p.ticket_id) details.push({ label: "Ticket", value: String(p.ticket_id) });
    if (p.amount_inr != null) details.push({ label: "Amount", value: `₹${p.amount_inr}`, highlight: true });
    if (p.cancellation_fee_inr != null) {
      const fee = Number(p.cancellation_fee_inr);
      details.push({
        label: "Cancel Fee",
        value: fee === 0 ? "₹0 (waived)" : `₹${fee}`,
        highlight: fee > 0,
      });
    }
    if (p.reason) details.push({ label: "Reason", value: String(p.reason) });
  }

  return details;
}
