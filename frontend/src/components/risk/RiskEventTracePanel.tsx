/**
 * RiskEventTracePanel.tsx — Wave 5 MVP 5.4 risk event trace (7th tab on /risk).
 *
 * 4 sections per iter 213 design:
 *   S0: FilterBar (severity / rule_id / hours / search code)
 *   S3: 24h HeatmapBar (events per hour, color = max severity)
 *   S1: EventListTable (paginated, click row → expand chain)
 *   S2: EventChainPanel (inline expand on row click)
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchRiskEvents,
  fetchRuleIds,
  type RiskEvent,
  type RiskEventSeverity,
} from "@/api/risk";

const SEVERITY_OPTIONS: Array<{ label: string; value: RiskEventSeverity | "" }> = [
  { label: "全部", value: "" },
  { label: "P0 (critical)", value: "p0" },
  { label: "P1 (high)", value: "p1" },
  { label: "P2 (med)", value: "p2" },
  { label: "INFO", value: "info" },
];

const HOURS_OPTIONS = [
  { label: "1 小时", value: 1 },
  { label: "6 小时", value: 6 },
  { label: "24 小时", value: 24 },
  { label: "7 天", value: 168 },
  { label: "30 天", value: 720 },
];

function severityBadge(sev: string): string {
  switch (sev.toLowerCase()) {
    case "p0":
      return "bg-red-500/20 text-red-400 border border-red-500/30";
    case "p1":
      return "bg-orange-500/20 text-orange-400 border border-orange-500/30";
    case "p2":
      return "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30";
    case "info":
      return "bg-slate-500/20 text-slate-400 border border-slate-500/30";
    default:
      return "bg-slate-700/40 text-slate-400 border border-slate-700";
  }
}

function severityHexColor(sev: string): string {
  switch (sev.toLowerCase()) {
    case "p0":
      return "#ef4444";
    case "p1":
      return "#f97316";
    case "p2":
      return "#eab308";
    case "info":
      return "#64748b";
    default:
      return "#475569";
  }
}

// ── S3 HeatmapBar ───────────────────────────────────────────────────────────

function HeatmapBar({ events }: { events: RiskEvent[] }) {
  // Group events by hour-of-day for last 24h (Asia/Shanghai timezone, 铁律 41)
  const buckets = useMemo(() => {
    const now = new Date();
    const slots = Array.from({ length: 24 }, () => ({ count: 0, maxSev: "" }));
    const sevRank = ["info", "p2", "p1", "p0"];

    for (const ev of events) {
      try {
        // Reviewer P1 iter 215: backend returns TIMESTAMPTZ::text format
        // "YYYY-MM-DD HH:MM:SS+TZ" (space separator). new Date() parses as
        // ISO-compliant in Chrome/Firefox, but Safari returns Invalid Date.
        // Normalize space → 'T' for ISO 8601 compliance.
        const isoSafe = ev.triggered_at.replace(" ", "T");
        const t = new Date(isoSafe);
        const hoursAgo = Math.floor((now.getTime() - t.getTime()) / 3_600_000);
        if (hoursAgo < 0 || hoursAgo >= 24) continue;
        const slot = slots[23 - hoursAgo];
        if (!slot) continue;
        slot.count++;
        const curRank = sevRank.indexOf(slot.maxSev);
        const newRank = sevRank.indexOf(ev.severity.toLowerCase());
        if (newRank > curRank) {
          slot.maxSev = ev.severity.toLowerCase();
        }
      } catch {
        // skip malformed timestamp
      }
    }
    return slots;
  }, [events]);

  const maxCount = Math.max(1, ...buckets.map((b) => b.count));

  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-800 p-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-2">
        24h 事件分布 (heatmap)
      </h3>
      <div className="flex items-end gap-1 h-20">
        {buckets.map((b, i) => {
          const height = Math.max(4, (b.count / maxCount) * 76);
          const color = b.count === 0 ? "#1e293b" : severityHexColor(b.maxSev);
          // Reviewer P1 iter 215: tooltip label off-by-one fix. slot[23-hoursAgo]
          // maps hoursAgo=0 (current hour, events 0-1h ago) → index 23.
          // So index i holds events from `(23-i)-(24-i)` hours ago.
          const ago = 23 - i;
          const agoLabel = ago === 0 ? "0–1h ago" : `${ago}–${ago + 1}h ago`;
          return (
            <div
              key={`heatmap-bar-${i}`}
              className="flex-1 rounded-t"
              style={{ height: `${height}px`, backgroundColor: color }}
              title={`${agoLabel} — ${b.count} events${b.maxSev ? ` (max ${b.maxSev})` : ""}`}
            />
          );
        })}
      </div>
      <div className="flex items-center justify-between text-[10px] text-slate-500 mt-1">
        <span>24h ago</span>
        <span>now</span>
      </div>
    </div>
  );
}

// ── S0 FilterBar ────────────────────────────────────────────────────────────

interface FilterState {
  severity: string;
  rule_id: string;
  hours: number;
}

function FilterBar({
  filter,
  ruleIds,
  onChange,
}: {
  filter: FilterState;
  ruleIds: string[];
  onChange: (next: FilterState) => void;
}) {
  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-800 p-4">
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">严重度</label>
          <select
            value={filter.severity}
            onChange={(e) => onChange({ ...filter, severity: e.target.value })}
            className="bg-slate-950 text-slate-200 text-xs px-2 py-1 rounded border border-slate-700"
          >
            {SEVERITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">规则</label>
          <select
            value={filter.rule_id}
            onChange={(e) => onChange({ ...filter, rule_id: e.target.value })}
            className="bg-slate-950 text-slate-200 text-xs px-2 py-1 rounded border border-slate-700 min-w-[160px]"
          >
            <option value="">全部规则</option>
            {ruleIds.map((rid) => (
              <option key={rid} value={rid}>
                {rid}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">时间窗口</label>
          <select
            value={filter.hours}
            onChange={(e) => onChange({ ...filter, hours: Number(e.target.value) })}
            className="bg-slate-950 text-slate-200 text-xs px-2 py-1 rounded border border-slate-700"
          >
            {HOURS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

// ── S1 EventListTable + S2 EventChainPanel ──────────────────────────────────

function EventListTable({
  events,
  expandedId,
  onToggle,
}: {
  events: RiskEvent[];
  expandedId: number | null;
  onToggle: (id: number) => void;
}) {
  if (events.length === 0) {
    return (
      <div className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
        <div className="text-sm text-slate-500">无匹配事件</div>
      </div>
    );
  }
  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-800 p-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-3">
        事件列表 ({events.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 border-b border-slate-800">
              <th className="text-left py-2 pr-3">时间</th>
              <th className="text-left py-2 pr-3">严重度</th>
              <th className="text-left py-2 pr-3">规则</th>
              <th className="text-left py-2 pr-3">代码</th>
              <th className="text-left py-2 pr-3">动作</th>
              <th className="text-left py-2">原因</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => (
              <Row
                key={ev.id}
                ev={ev}
                expanded={expandedId === ev.id}
                onClick={() => onToggle(ev.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Row({
  ev,
  expanded,
  onClick,
}: {
  ev: RiskEvent;
  expanded: boolean;
  onClick: () => void;
}) {
  return (
    <>
      <tr
        onClick={onClick}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClick();
          }
        }}
        className="border-b border-slate-800/50 cursor-pointer hover:bg-slate-950/40 focus-visible:outline focus-visible:outline-1 focus-visible:outline-sky-400"
      >
        <td className="py-2 pr-3 text-slate-400 font-mono text-[10px]">
          {ev.triggered_at.slice(11, 19)} {/* HH:MM:SS */}
        </td>
        <td className="py-2 pr-3">
          <span
            className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${severityBadge(ev.severity)}`}
          >
            {ev.severity.toUpperCase()}
          </span>
        </td>
        <td className="py-2 pr-3 text-slate-300 font-mono">{ev.rule_id}</td>
        <td className="py-2 pr-3 text-slate-400">{ev.code ?? "—"}</td>
        <td className="py-2 pr-3 text-slate-400">{ev.action_taken ?? "—"}</td>
        <td className="py-2 text-slate-300 max-w-md truncate">{ev.reason}</td>
      </tr>
      {expanded && (
        <tr className="bg-slate-950/60">
          <td colSpan={6} className="px-4 py-3">
            <EventChainDetail ev={ev} />
          </td>
        </tr>
      )}
    </>
  );
}

function EventChainDetail({ ev }: { ev: RiskEvent }) {
  return (
    <div className="space-y-2 text-xs">
      <div>
        <span className="text-slate-500">完整原因:</span>{" "}
        <span className="text-slate-200">{ev.reason}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
        <Cell label="strategy_id" value={ev.strategy_id.slice(0, 8)} />
        <Cell label="shares" value={ev.shares?.toString() ?? "—"} />
        <Cell label="cadence" value={ev.cadence ?? "—"} />
        <Cell
          label="detection_latency_ms"
          value={ev.detection_latency_ms != null ? `${ev.detection_latency_ms}ms` : "—"}
        />
      </div>
      <div>
        <div className="text-slate-500 mb-1">执行链 (execution_plans):</div>
        {ev.chain ? (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px] bg-slate-950/40 rounded p-2">
            <Cell label="plan_id" value={ev.chain.plan_id?.slice(0, 8) ?? "—"} />
            <Cell label="status" value={ev.chain.status ?? "—"} />
            <Cell label="action" value={ev.chain.action ?? "—"} />
            <Cell label="qty" value={ev.chain.qty?.toString() ?? "—"} />
            <Cell label="user_decision" value={ev.chain.user_decision ?? "—"} />
            <Cell label="broker_order_id" value={ev.chain.broker_order_id ?? "—"} />
          </div>
        ) : (
          <div className="text-slate-500 text-[11px]">无关联执行计划</div>
        )}
      </div>
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-slate-500">{label}:</span>{" "}
      <span className="text-slate-300 font-mono">{value}</span>
    </div>
  );
}

// ── Main panel ──────────────────────────────────────────────────────────────

export function RiskEventTracePanel() {
  const [filter, setFilter] = useState<FilterState>({
    severity: "",
    rule_id: "",
    hours: 24,
  });
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const ruleIdsQ = useQuery({
    queryKey: ["risk-event-trace", "rule-ids"],
    queryFn: fetchRuleIds,
    staleTime: 5 * 60_000,
  });

  const eventsQ = useQuery({
    queryKey: [
      "risk-event-trace",
      "events",
      filter.severity,
      filter.rule_id,
      filter.hours,
    ],
    queryFn: () =>
      fetchRiskEvents({
        severity: filter.severity || undefined,
        rule_id: filter.rule_id || undefined,
        hours: filter.hours,
        limit: 100,
        include_chain: true,
      }),
    refetchInterval: 60_000,
  });

  const events = eventsQ.data?.events ?? [];
  const ruleIds = ruleIdsQ.data?.rule_ids ?? [];

  function toggleExpand(id: number) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  return (
    <div className="space-y-3">
      {eventsQ.error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-sm text-red-400">
          事件加载失败: {eventsQ.error instanceof Error ? eventsQ.error.message : "unknown"}
        </div>
      )}
      {/* Reviewer P2 iter 215: surface ruleIdsQ error (was silently swallowed,
          rule dropdown would show empty without user feedback per 铁律 33). */}
      {ruleIdsQ.error && (
        <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 p-3 text-xs text-amber-400">
          规则列表加载失败: {ruleIdsQ.error instanceof Error ? ruleIdsQ.error.message : "unknown"}
        </div>
      )}
      <FilterBar filter={filter} ruleIds={ruleIds} onChange={setFilter} />
      <HeatmapBar events={events} />
      {eventsQ.isLoading && !eventsQ.data ? (
        <div className="rounded-lg bg-slate-900/60 border border-slate-800 p-5 text-sm text-slate-500">
          加载中...
        </div>
      ) : (
        <EventListTable
          events={events}
          expandedId={expandedId}
          onToggle={toggleExpand}
        />
      )}
    </div>
  );
}
