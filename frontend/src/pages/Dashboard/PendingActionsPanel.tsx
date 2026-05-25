/**
 * PendingActionsPanel — Dashboard 待处理事项面板.
 *
 * iter 139 W2-F F8 closure — backend `GET /api/dashboard/pending-actions`
 * (backend/app/api/dashboard.py:67) previously DARK (fetchPendingActions
 * wrapper existed in dashboard.ts:31 but 0 consumer page). This panel
 * adds the consumer + surfaces 熔断/健康异常/管道失败 events to operator.
 *
 * Backend SSOT: backend/app/api/dashboard.py:67-81
 *   GET /api/dashboard/pending-actions → list[{type, severity, message, time}]
 * Response shape: types/dashboard.ts:23-28 PendingAction
 *
 * Severity → color mapping (A股惯例: 涨红跌绿 reversed):
 *   critical → C.up (red, urgent attention)
 *   warning  → C.warn (yellow, monitoring)
 *   info     → C.info (blue, FYI)
 *
 * Type → label mapping:
 *   circuit_breaker → "熔断" (L1-L4 风控触发)
 *   health → "健康" (PG/Redis/disk/数据新鲜度)
 *   pipeline → "管道" (Celery/Beat/schtask 失败)
 *
 * 沿用 AlertsPanel.tsx pattern — pure presentational + parent passes data array.
 */

import { Card, CardHeader } from "@/components/shared";
import { C } from "@/theme";
import { AlertOctagon, AlertTriangle, Info, Clock } from "lucide-react";
import type { PendingAction } from "@/types/dashboard";

const SEVERITY_CONFIG: Record<
  PendingAction["severity"],
  { color: string; icon: typeof AlertOctagon; label: string }
> = {
  critical: { color: C.up, icon: AlertOctagon, label: "紧急" },
  warning: { color: C.warn, icon: AlertTriangle, label: "警告" },
  info: { color: C.info, icon: Info, label: "提示" },
};

const TYPE_LABEL: Record<PendingAction["type"], string> = {
  circuit_breaker: "熔断",
  health: "健康",
  pipeline: "管道",
};

function formatTimeAgo(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  const ms = Date.now() - date.getTime();
  const min = Math.floor(ms / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min}分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}小时前`;
  const day = Math.floor(hr / 24);
  return `${day}天前`;
}

export function PendingActionsPanel({ actions }: { actions: PendingAction[] }) {
  // Sort: critical first, then warning, then info; within severity, recent first
  const sortedActions = [...actions].sort((a, b) => {
    const sevOrder = { critical: 0, warning: 1, info: 2 };
    const sevDiff = sevOrder[a.severity] - sevOrder[b.severity];
    if (sevDiff !== 0) return sevDiff;
    return (b.time ?? "").localeCompare(a.time ?? "");
  });

  return (
    <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 320 }}>
      <CardHeader
        title="待处理事项"
        titleEn="Pending Actions"
        right={
          actions.length > 0 ? (
            <span
              className="w-5 h-5 rounded-full flex items-center justify-center"
              style={{
                fontSize: 10,
                color: "#fff",
                background: actions.some((a) => a.severity === "critical") ? C.up : C.warn,
                fontWeight: 600,
              }}
            >
              {actions.length}
            </span>
          ) : null
        }
      />
      <div className="flex-1 overflow-y-auto p-3">
        {sortedActions.length === 0 ? (
          <div className="text-center py-8" style={{ fontSize: 12, color: C.text4 }}>
            暂无待处理事项
          </div>
        ) : (
          <div className="space-y-2">
            {sortedActions.slice(0, 20).map((action, i) => {
              const cfg = SEVERITY_CONFIG[action.severity];
              const IconCmp = cfg.icon;
              return (
                <div
                  key={`${action.type}-${i}`}
                  className="rounded-lg px-3 py-2.5"
                  style={{
                    background: `${cfg.color}06`,
                    border: `1px solid ${cfg.color}15`,
                  }}
                >
                  <div className="flex items-center gap-2">
                    <IconCmp size={12} color={cfg.color} />
                    <span
                      className="shrink-0 px-1.5 py-0.5 rounded"
                      style={{
                        fontSize: 9,
                        color: cfg.color,
                        fontWeight: 700,
                        fontFamily: C.mono,
                        background: `${cfg.color}12`,
                      }}
                    >
                      {TYPE_LABEL[action.type]} · {cfg.label}
                    </span>
                    <span
                      className="ml-auto shrink-0 flex items-center gap-1"
                      style={{ fontSize: 10, color: C.text4 }}
                    >
                      <Clock size={9} />
                      {formatTimeAgo(action.time)}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: C.text2,
                      marginTop: 4,
                      paddingLeft: 20,
                      lineHeight: 1.5,
                    }}
                  >
                    {action.message}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
