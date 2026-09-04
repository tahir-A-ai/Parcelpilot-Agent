// ============================================================
// ToolBadges – renders the ordered list of tool calls made
// during an agent run as visual pills below the bot message.
// ============================================================

import { Database, FileSearch, Zap } from "lucide-react";
import type { ToolLog } from "../types";
import { getToolBadgeProps } from "../types";

interface ToolBadgesProps {
  logs: ToolLog[];
}

function BadgeIcon({ icon }: { icon: string }) {
  const size = 10;
  if (icon === "db")     return <Database size={size} />;
  if (icon === "search") return <FileSearch size={size} />;
  if (icon === "action") return <Zap size={size} />;
  return null;
}

export default function ToolBadges({ logs }: ToolBadgesProps) {
  if (!logs || logs.length === 0) return null;

  // De-duplicate: same tool_name appearing consecutively collapses to 1 badge
  const unique = logs.filter(
    (log, i, arr) => i === 0 || arr[i - 1].tool_name !== log.tool_name
  );

  return (
    <div className="tool-badges">
      {unique.map((log, i) => {
        const { label, variant, icon } = getToolBadgeProps(log.tool_name);
        return (
          <span key={i} className={`tool-badge ${variant}`} title={`Step ${log.step}: ${log.tool_name}`}>
            <BadgeIcon icon={icon} />
            {label}
          </span>
        );
      })}
    </div>
  );
}
