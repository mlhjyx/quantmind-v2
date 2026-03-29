import { C } from "@/theme";

type Priority = "P0" | "P1" | "P2" | "P3";
type Status = "running" | "stopped" | "warning" | "error" | "pending" | "success";

const PRIORITY_COLORS: Record<Priority, string> = {
  P0: C.down,
  P1: C.warn,
  P2: C.info,
  P3: C.text3,
};

const STATUS_COLORS: Record<Status, string> = {
  running: C.up,
  success: C.up,
  stopped: C.text3,
  pending: C.text3,
  warning: C.warn,
  error: C.down,
};

interface StatusBadgeProps {
  label: string;
  /** Explicit color overrides priority/status presets */
  color?: string;
  priority?: Priority;
  status?: Status;
}

export function StatusBadge({ label, color, priority, status }: StatusBadgeProps) {
  const resolvedColor =
    color ??
    (priority ? PRIORITY_COLORS[priority] : undefined) ??
    (status ? STATUS_COLORS[status] : C.text3);

  return (
    <span
      className="px-2 py-0.5 rounded-full"
      style={{
        fontSize: 9,
        color: resolvedColor,
        background: `${resolvedColor}18`,
        fontWeight: 600,
        letterSpacing: 0.3,
      }}
    >
      {label}
    </span>
  );
}
