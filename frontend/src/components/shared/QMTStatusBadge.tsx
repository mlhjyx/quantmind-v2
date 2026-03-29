import { useQuery } from "@tanstack/react-query";
import { C } from "@/theme";
import apiClient from "@/api/client";

interface QMTHealth {
  execution_mode: string;
  state: string;
  account_id: string | null;
  connected_at: string | null;
  last_error: string | null;
  is_healthy: boolean;
  account_asset?: {
    total_asset: number;
    cash: number;
    market_value: number;
  };
}

const STATE_CONFIG: Record<string, { label: string; color: string }> = {
  connected: { label: "QMT", color: C.up },
  connecting: { label: "QMT", color: C.warn },
  disconnected: { label: "QMT", color: C.down },
  error: { label: "QMT", color: C.down },
  disabled: { label: "SimBroker", color: C.text3 },
};

export function QMTStatusBadge() {
  const { data } = useQuery<QMTHealth>({
    queryKey: ["qmt-health"],
    queryFn: () => apiClient.get("/health/qmt").then((r) => r.data),
    refetchInterval: 30_000,
    retry: 1,
  });

  if (!data) return null;

  const fallback = STATE_CONFIG["disabled"];
  const cfg = STATE_CONFIG[data.state] ?? fallback;
  const dotColor = data.is_healthy ? cfg.color : C.down;

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full"
      style={{
        fontSize: 10,
        color: cfg.color,
        background: `${cfg.color}15`,
        fontWeight: 600,
      }}
      title={
        data.state === "disabled"
          ? "Paper Trading (SimBroker)"
          : `QMT ${data.state} | ${data.account_id ?? ""}`
      }
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: dotColor,
          display: "inline-block",
        }}
      />
      {cfg.label}
    </span>
  );
}
