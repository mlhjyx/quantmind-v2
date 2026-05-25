import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
// Frontend Design v3 §4.3: raw axios → apiClient SSOT (Audit Finding #5)
import apiClient from "@/api/client";
import { Shield, AlertTriangle, History, TrendingUp, ArrowDown, ArrowUp, Activity } from "lucide-react";
// iter 140 W2-F F5 — getPaperStrategyId for real UUID (sibling iter 137 P0 fix)
import { getPaperStrategyId } from "@/api/system";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, TabButtons, ChartTooltip } from "@/components/shared";
import { SafetyControlPanel } from "@/components/safety/SafetyControlPanel";
import { fetchCircuitBreakerState } from "@/api/dashboard";
import type { CircuitBreakerState } from "@/types/dashboard";
import { useRiskEventsSSE } from "@/hooks/useRiskEventsSSE";

// ── Types ──
interface OverviewMetric { label: string; value: string; color?: string; }
interface RiskLimit      { name: string; current: string; limit: string; usage: number; status: string; }
interface StressTest     { scenario: string; impact: number; probability: string; recovery: string; }
interface VarPoint       { date: string; var95: number; var99: number; limit: number; }
interface ExposureItem   { factor: string; exposure: number; limit: number; color: string; }


// Session 58 round-5 ADR-084 Phase 1 closure: SSE EventSource live events tab.
// 反 polling waste — sub-second latency for P0/P1 alerts via server push.
// 关联 hooks/useRiskEventsSSE.ts (round-4 NEW hook) + backend/app/api/sse.py (round-2 P4).
function LiveRiskEventsPanel() {
  const { events, isConnected, lastHeartbeatAt, error, reconnect } = useRiskEventsSSE({
    maxBuffer: 50,
  });

  return (
    <Card>
      <CardHeader title="实时风控事件 (SSE)" titleEn="Live Risk Events Stream" />
      <div className="px-4 py-3">
        <div className="flex items-center gap-3 mb-3" style={{ fontSize: 11 }}>
          <span
            className="flex items-center gap-1.5 px-2 py-0.5 rounded"
            style={{
              background: isConnected ? `${C.down}15` : `${C.up}15`,
              color: isConnected ? C.down : C.up,
              fontWeight: 600,
            }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: isConnected ? C.down : C.up,
                animation: isConnected ? "pulse 2s infinite" : undefined,
              }}
            />
            {isConnected ? "已连接" : "未连接"}
          </span>
          {lastHeartbeatAt && (
            <span style={{ color: C.text4 }}>
              心跳: <span style={{ color: C.text3, fontFamily: C.mono }}>
                {lastHeartbeatAt.toLocaleTimeString("zh-CN")}
              </span>
            </span>
          )}
          {error && (
            <span style={{ color: C.warn }}>错误: {error}</span>
          )}
          <button
            onClick={reconnect}
            className="ml-auto px-2 py-0.5 rounded cursor-pointer"
            style={{ background: C.bg3, color: C.text3, fontSize: 10 }}
          >
            重新连接
          </button>
        </div>
        {events.length === 0 ? (
          <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>
            等待事件流 ... 当 risk_event_log 有新 row 时实时显示在此 (sub-second latency).
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {[...events].reverse().map((ev) => (
              <div
                key={ev.id}
                className="px-3 py-2 rounded"
                style={{
                  background: C.bg2,
                  border: `1px solid ${C.border}`,
                  fontSize: 11,
                }}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="px-1.5 py-0.5 rounded font-mono"
                    style={{
                      fontSize: 9,
                      background: `${C.up}15`,
                      color: C.up,
                      fontWeight: 600,
                    }}
                  >
                    {ev.severity}
                  </span>
                  <span style={{ color: C.text2, fontWeight: 500 }}>{ev.rule_id}</span>
                  {ev.code && (
                    <span style={{ color: C.text3, fontFamily: C.mono }}>{ev.code}</span>
                  )}
                  <span className="ml-auto" style={{ color: C.text4, fontFamily: C.mono }}>
                    {new Date(ev.triggered_at).toLocaleString("zh-CN")}
                  </span>
                </div>
                {ev.reason && (
                  <div style={{ color: C.text3, lineHeight: 1.5 }}>{ev.reason}</div>
                )}
                {ev.action_taken && (
                  <div className="mt-1" style={{ color: C.info, fontSize: 10 }}>
                    Action: {ev.action_taken}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

// ───────────────────────────────────────────────────────────────
// iter 140 W2-F F5 — Status History + Summary panel
// ───────────────────────────────────────────────────────────────
// Closes W2-F audit A2 (`GET /api/risk/history/{strategy_id}`, risk.py:146)
// + A3 (`GET /api/risk/summary/{strategy_id}`, risk.py:187) both DARK pre-iter
// 140 despite backend service existing. UUID strategy_id via getPaperStrategyId
// (iter 137 P0 fix canonical pattern).

interface RiskTransition {
  trade_date: string;
  prev_level: number;
  new_level: number;
  transition_type: string;
  reason: string | null;
  metrics: Record<string, number> | null;
}

interface RiskSummaryResponse {
  current_level?: number;
  current_level_name?: string;
  days_in_current_state?: number;
  total_escalations?: number;
  total_recoveries?: number;
  last_transition_date?: string | null;
  max_level_30d?: number;
  // 后端 schema 容错 — 实际字段可能扩展
  [k: string]: unknown;
}

function formatTransitionType(t: string): { label: string; color: string; icon: typeof ArrowUp } {
  switch (t) {
    case "escalate":
      return { label: "升级", color: C.up, icon: ArrowUp };
    case "recover":
      return { label: "恢复", color: C.down, icon: ArrowDown };
    case "manual_reset":
      return { label: "强制重置", color: C.warn, icon: Activity };
    case "force_close":
      return { label: "强制平仓", color: "#dc2626", icon: Activity };
    default:
      return { label: t, color: C.text3, icon: Activity };
  }
}

function RiskStatusHistoryPanel() {
  // Fetch real paper_strategy_id UUID (iter 137 P0 fix canonical)
  const { data: paperSid } = useQuery({
    queryKey: ["system-paper-strategy-id"],
    queryFn: () => getPaperStrategyId(),
    staleTime: 60 * 60 * 1000,
  });
  const strategyId =
    paperSid?.configured && paperSid.paper_strategy_id ? paperSid.paper_strategy_id : null;

  const historyQ = useQuery({
    queryKey: ["risk-history", strategyId],
    queryFn: async () => {
      if (!strategyId) return [] as RiskTransition[];
      const { data } = await apiClient.get<RiskTransition[]>(`/risk/history/${strategyId}`, {
        params: { execution_mode: "paper", limit: 50 },
      });
      return data;
    },
    enabled: strategyId != null,
    staleTime: 30_000,
  });

  const summaryQ = useQuery({
    queryKey: ["risk-summary", strategyId],
    queryFn: async () => {
      if (!strategyId) return null;
      const { data } = await apiClient.get<RiskSummaryResponse>(`/risk/summary/${strategyId}`, {
        params: { execution_mode: "paper" },
      });
      return data;
    },
    enabled: strategyId != null,
    staleTime: 30_000,
  });

  if (!strategyId) {
    return (
      <Card>
        <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>
          <AlertTriangle size={24} color={C.warn} className="mx-auto mb-2" />
          <div>PAPER_STRATEGY_ID 未配置 — 历史/概览不可用</div>
          <div style={{ marginTop: 4 }}>请配置 backend/.env 后刷新</div>
        </div>
      </Card>
    );
  }

  const summary = summaryQ.data;
  const transitions = historyQ.data ?? [];

  return (
    <div className="space-y-3">
      {/* Summary 概览卡片 */}
      <Card>
        <CardHeader title="风控概览" titleEn="Risk Summary" />
        <div className="p-4">
          {summaryQ.isLoading ? (
            <div style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
          ) : summaryQ.isError ? (
            <div style={{ fontSize: 12, color: C.up }}>
              概览加载失败: {summaryQ.error instanceof Error ? summaryQ.error.message : "未知错误"}
            </div>
          ) : !summary ? (
            <div style={{ fontSize: 12, color: C.text4 }}>暂无概览数据</div>
          ) : (
            <div className="grid grid-cols-4 gap-3">
              <div className="rounded-lg p-3" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 10, color: C.text4, marginBottom: 4 }}>当前等级</div>
                <div style={{ fontSize: 18, color: C.text1, fontWeight: 600, fontFamily: C.mono }}>
                  L{summary.current_level ?? "—"}{" "}
                  <span style={{ fontSize: 11, color: C.text3, fontFamily: C.font }}>
                    {summary.current_level_name ?? ""}
                  </span>
                </div>
              </div>
              <div className="rounded-lg p-3" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 10, color: C.text4, marginBottom: 4 }}>当前等级保持</div>
                <div style={{ fontSize: 18, color: C.text1, fontWeight: 600 }}>
                  {summary.days_in_current_state ?? "—"} <span style={{ fontSize: 11, color: C.text3 }}>天</span>
                </div>
              </div>
              <div className="rounded-lg p-3" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 10, color: C.text4, marginBottom: 4 }}>累计升级</div>
                <div style={{ fontSize: 18, color: C.up, fontWeight: 600 }}>
                  {summary.total_escalations ?? "—"}
                </div>
              </div>
              <div className="rounded-lg p-3" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 10, color: C.text4, marginBottom: 4 }}>累计恢复</div>
                <div style={{ fontSize: 18, color: C.down, fontWeight: 600 }}>
                  {summary.total_recoveries ?? "—"}
                </div>
              </div>
            </div>
          )}
          {summary?.last_transition_date && (
            <div className="mt-3" style={{ fontSize: 11, color: C.text3 }}>
              最近一次状态变更: <span style={{ color: C.text2 }}>{summary.last_transition_date}</span>
              {summary.max_level_30d != null && (
                <>
                  {" · "}30 天最高等级: <span style={{ color: C.up, fontFamily: C.mono }}>L{summary.max_level_30d}</span>
                </>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* History 状态变更历史 */}
      <Card>
        <CardHeader
          title="状态变更历史"
          titleEn="Transition History"
          right={
            <span style={{ fontSize: 10, color: C.text4 }}>
              <History size={11} className="inline" /> 最近 {transitions.length} 条
            </span>
          }
        />
        <div className="p-4">
          {historyQ.isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-12 rounded-lg animate-pulse" style={{ background: C.bg2 }} />
              ))}
            </div>
          ) : historyQ.isError ? (
            <div style={{ fontSize: 12, color: C.up }}>
              历史加载失败: {historyQ.error instanceof Error ? historyQ.error.message : "未知错误"}
            </div>
          ) : transitions.length === 0 ? (
            <div className="text-center py-6" style={{ fontSize: 12, color: C.text4 }}>
              <TrendingUp size={20} color={C.down} className="mx-auto mb-2" />
              暂无状态变更记录 (策略稳定运行)
            </div>
          ) : (
            <div className="space-y-2">
              {transitions.map((t, i) => {
                const cfg = formatTransitionType(t.transition_type);
                const IconCmp = cfg.icon;
                return (
                  <div
                    key={`${t.trade_date}-${i}`}
                    className="rounded-lg px-3 py-2"
                    style={{ background: `${cfg.color}08`, border: `1px solid ${cfg.color}25` }}
                  >
                    <div className="flex items-center gap-2">
                      <IconCmp size={14} color={cfg.color} />
                      <span
                        className="px-2 py-0.5 rounded"
                        style={{ fontSize: 9, color: cfg.color, fontWeight: 700, fontFamily: C.mono, background: `${cfg.color}12` }}
                      >
                        {cfg.label}
                      </span>
                      <span style={{ fontSize: 11, color: C.text2, fontFamily: C.mono }}>
                        L{t.prev_level} → L{t.new_level}
                      </span>
                      <span className="ml-auto" style={{ fontSize: 10, color: C.text4, fontFamily: C.mono }}>
                        {t.trade_date}
                      </span>
                    </div>
                    {t.reason && (
                      <div style={{ fontSize: 11, color: C.text3, marginTop: 4, paddingLeft: 22 }}>
                        {t.reason}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function usageColor(usage: number) {
  if (usage >= 90) return C.down;
  if (usage >= 70) return C.warn;
  return C.up;
}

/**
 * Map circuit_breaker level → risk badge label + color (Frontend Design v3 §3.1.3).
 * Replaces hardcoded "LOW" with real backend state.
 * 注: 风险语义用 down(绿)=安全 / warn(黄)=注意 / up(红)=危险 顺序, 跟股票涨跌色相反.
 */
function riskBadge(level: number | null): { label: string; color: string } {
  if (level == null) return { label: "—", color: C.text4 };
  if (level === 0) return { label: "LOW", color: C.down };
  if (level === 1) return { label: "WARN", color: C.warn };
  if (level === 2) return { label: "ELEVATED", color: "#fb923c" };
  if (level === 3) return { label: "HIGH", color: C.up };
  return { label: "CRITICAL", color: "#dc2626" };
}

export default function RiskManagement() {
  const [tab, setTab] = useState("风控总览");

  const [overviewMetrics, setOverviewMetrics] = useState<OverviewMetric[] | null>(null);
  const [varData, setVarData]                 = useState<VarPoint[] | null>(null);
  const [exposure, setExposure]               = useState<ExposureItem[] | null>(null);
  const [stressTests, setStressTests]         = useState<StressTest[] | null>(null);
  const [riskLimits, setRiskLimits]           = useState<RiskLimit[] | null>(null);
  const [cbState, setCbState]                 = useState<CircuitBreakerState | null>(null);
  const [loading, setLoading]                 = useState(true);
  const [fetchError, setFetchError]           = useState(false);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        // 先请求live数据，如果为空fallback到paper
        let mode = "live";
        const [overview, limits, stress] = await Promise.allSettled([
          apiClient.get<{ metrics?: OverviewMetric[]; var_series?: VarPoint[]; exposure?: ExposureItem[] }>("/risk/overview", { params: { execution_mode: mode } }),
          apiClient.get<RiskLimit[]>("/risk/limits", { params: { execution_mode: mode } }),
          apiClient.get<StressTest[]>("/risk/stress-tests", { params: { execution_mode: mode } }),
        ]);
        if (!live) return;

        // 检查live数据是否足够
        const liveMetrics = overview.status === "fulfilled" ? overview.value.data.metrics : undefined;
        const liveEmpty = !liveMetrics || liveMetrics.length === 0;

        // 如果live数据不足，fallback到paper
        if (liveEmpty && mode === "live") {
          mode = "paper";
          const [ov2, li2, st2] = await Promise.allSettled([
            apiClient.get<{ metrics?: OverviewMetric[]; var_series?: VarPoint[]; exposure?: ExposureItem[] }>("/risk/overview", { params: { execution_mode: mode } }),
            apiClient.get<RiskLimit[]>("/risk/limits", { params: { execution_mode: mode } }),
            apiClient.get<StressTest[]>("/risk/stress-tests", { params: { execution_mode: mode } }),
          ]);
          if (!live) return;
          if (ov2.status === "fulfilled") {
            const d = ov2.value.data;
            if (d.metrics)    setOverviewMetrics(d.metrics);
            if (d.var_series) setVarData(d.var_series);
            if (d.exposure)   setExposure(d.exposure);
          }
          if (li2.status === "fulfilled") setRiskLimits(li2.value.data);
          if (st2.status === "fulfilled") setStressTests(st2.value.data);
        } else {
          const allFailed =
            overview.status === "rejected" &&
            limits.status === "rejected" &&
            stress.status === "rejected";
          if (allFailed) {
            setFetchError(true);
          } else {
            if (overview.status === "fulfilled") {
              const d = overview.value.data;
              if (d.metrics)    setOverviewMetrics(d.metrics);
              if (d.var_series) setVarData(d.var_series);
              if (d.exposure)   setExposure(d.exposure);
            }
            if (limits.status === "fulfilled") setRiskLimits(limits.value.data);
            if (stress.status === "fulfilled") setStressTests(stress.value.data);
          }
        }
      } catch {
        if (live) setFetchError(true);
      } finally {
        if (live) setLoading(false);
      }
    };
    void load();
    // Circuit breaker state (Frontend Design v3 §3.1.3 — fix hardcoded LOW)
    fetchCircuitBreakerState()
      .then((cb) => { if (live) setCbState(cb); })
      .catch(() => { if (live) setCbState(null); });

    const id = setInterval(() => void load(), 30_000);
    const cbId = setInterval(() => {
      void fetchCircuitBreakerState()
        .then((cb) => { if (live) setCbState(cb); })
        .catch(() => {});
    }, 10_000);
    return () => { live = false; clearInterval(id); clearInterval(cbId); };
  }, []);

  const warnCount     = riskLimits?.filter((r) => r.status === "warn").length ?? 0;
  const criticalCount = riskLimits?.filter((r) => r.status === "critical").length ?? 0;
  const okCount       = riskLimits?.filter((r) => r.status === "ok").length ?? 0;

  return (
    <>
      <PageHeader title="风控管理" titleEn="Risk Management">
        <TabButtons
          tabs={["风控总览", "状态历史", "压力测试", "限额监控", "紧急控制", "实时事件"]}
          active={tab}
          onChange={setTab}
        />
        {(() => {
          const badge = riskBadge(cbState?.level ?? null);
          return (
            <div
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg"
              style={{ background: `${badge.color}12`, border: `1px solid ${badge.color}35` }}
              title={cbState ? `L${cbState.level} · ${cbState.level_name}` : "熔断状态未知"}
            >
              <Shield size={14} color={badge.color} />
              <span style={{ fontSize: 11, color: badge.color, fontWeight: 500 }}>
                风险等级: {badge.label}
              </span>
            </div>
          );
        })()}
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3">
        {fetchError && (
          <div className="px-4 py-2 rounded-lg text-center" style={{ background: `${C.down}10`, border: `1px solid ${C.down}30`, fontSize: 12, color: C.down }}>
            数据加载失败，风控数据暂不可用
          </div>
        )}

        {tab === "风控总览" && (
          <>
            <div className="grid grid-cols-6 gap-3">
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <Card key={i} className="px-3.5 py-2.5">
                    <div className="h-2.5 w-12 rounded animate-pulse mb-2" style={{ background: C.bg3 }} />
                    <div className="h-5 w-16 rounded animate-pulse" style={{ background: C.bg3 }} />
                  </Card>
                ))
              ) : !overviewMetrics || overviewMetrics.length === 0 ? (
                <div className="col-span-6 text-center py-4" style={{ fontSize: 12, color: C.text4 }}>暂无数据</div>
              ) : overviewMetrics.map((m) => (
                <Card key={m.label} className="px-3.5 py-2.5">
                  <div style={{ fontSize: 9, color: C.text4 }}>{m.label}</div>
                  <div style={{ fontSize: 16, fontFamily: C.mono, fontWeight: 700, color: m.color ?? C.text1 }}>{m.value}</div>
                </Card>
              ))}
            </div>

            <div className="grid grid-cols-12 gap-3">
              <Card className="col-span-8 flex flex-col overflow-hidden">
                <CardHeader title="VaR走势" titleEn="Value at Risk" />
                <div className="px-4 pt-2 flex-1" style={{ minHeight: 240 }}>
                  {loading ? (
                    <div className="h-full flex items-center justify-center" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
                  ) : !varData || varData.length === 0 ? (
                    <div className="h-full flex items-center justify-center" style={{ fontSize: 12, color: C.text4 }}>暂无数据</div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={varData} margin={{ top: 8, right: 15, bottom: 0, left: -10 }}>
                        <defs>
                          <linearGradient id="varFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={C.warn} stopOpacity={0.15} />
                            <stop offset="100%" stopColor={C.warn} stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid stroke={`${C.border}60`} strokeDasharray="3 6" vertical={false} />
                        <XAxis dataKey="date" tick={{ fill: C.text4, fontSize: 10 }} axisLine={false} tickLine={false} interval={9} />
                        <YAxis tick={{ fill: C.text4, fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
                        <Tooltip content={<ChartTooltip />} />
                        <Area name="95%VaR" dataKey="var95" stroke={C.warn} strokeWidth={2} fill="url(#varFill)" dot={false} />
                        <Line name="99%VaR" dataKey="var99" stroke={C.down} strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
                        <Line name="限额"   dataKey="limit" stroke={C.text4} strokeWidth={1} strokeDasharray="8 4" dot={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </Card>

              <Card className="col-span-4">
                <CardHeader title="因子暴露" titleEn="Factor Exposure" />
                <div className="p-3 space-y-2.5">
                  {loading ? (
                    <div className="text-center py-4" style={{ fontSize: 11, color: C.text4 }}>加载中...</div>
                  ) : !exposure || exposure.length === 0 ? (
                    <div className="text-center py-4" style={{ fontSize: 11, color: C.text4 }}>暂无数据</div>
                  ) : exposure.map((e) => (
                    <div key={e.factor}>
                      <div className="flex items-center justify-between mb-1">
                        <span style={{ fontSize: 11, color: C.text2 }}>{e.factor}</span>
                        <span style={{ fontSize: 11, fontFamily: C.mono, color: e.exposure >= 0 ? C.up : C.down, fontWeight: 600 }}>
                          {e.exposure >= 0 ? "+" : ""}{e.exposure.toFixed(2)}
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full overflow-hidden flex" style={{ background: C.bg2 }}>
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${(Math.abs(e.exposure) / e.limit) * 50}%`,
                            marginLeft: e.exposure < 0 ? `${50 - (Math.abs(e.exposure) / e.limit) * 50}%` : "50%",
                            background: e.color,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </>
        )}

        {tab === "压力测试" && (
          <Card>
            <CardHeader title="压力测试场景" titleEn="Stress Testing" />
            <div className="p-3">
              {loading ? (
                <div className="text-center py-8" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
              ) : !stressTests || stressTests.length === 0 ? (
                <div className="text-center py-8" style={{ fontSize: 12, color: C.text4 }}>暂无数据</div>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  {stressTests.map((s) => (
                    <div key={s.scenario} className="rounded-xl p-4" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
                      <div style={{ fontSize: 13, color: C.text1, fontWeight: 500, marginBottom: 8 }}>{s.scenario}</div>
                      <div style={{ fontSize: 28, fontFamily: C.mono, fontWeight: 700, color: C.down, marginBottom: 8 }}>{s.impact}%</div>
                      <div className="flex items-center justify-between" style={{ fontSize: 10, color: C.text3 }}>
                        <span>
                          概率:{" "}
                          <span style={{ color: s.probability === "极低" || s.probability === "低" ? C.up : C.warn }}>
                            {s.probability}
                          </span>
                        </span>
                        <span>恢复: {s.recovery}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>
        )}

        {tab === "紧急控制" && <SafetyControlPanel />}

        {/* iter 140 W2-F F5 closure — status history + summary surface */}
        {tab === "状态历史" && <RiskStatusHistoryPanel />}

        {tab === "实时事件" && <LiveRiskEventsPanel />}

        {tab === "限额监控" && (
          <Card>
            <CardHeader
              title="风控限额"
              titleEn="Risk Limits"
              right={
                <div className="flex gap-3" style={{ fontSize: 10 }}>
                  <span style={{ color: C.up }}>● 正常 {okCount}</span>
                  <span style={{ color: C.warn }}>● 预警 {warnCount}</span>
                  {criticalCount > 0 && <span style={{ color: C.down }}>● 临界 {criticalCount}</span>}
                </div>
              }
            />
            <div className="p-3 space-y-2">
              {loading ? (
                <div className="text-center py-8" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
              ) : !riskLimits || riskLimits.length === 0 ? (
                <div className="text-center py-8" style={{ fontSize: 12, color: C.text4 }}>暂无数据</div>
              ) : riskLimits.map((r) => {
                const isWarn     = r.status === "warn";
                const isCritical = r.status === "critical";
                const hlColor    = isCritical ? C.down : isWarn ? C.warn : null;
                return (
                  <div
                    key={r.name}
                    className="flex items-center gap-4 px-4 py-3 rounded-xl"
                    style={{
                      background: hlColor ? `${hlColor}06` : C.bg2,
                      border: `1px solid ${hlColor ? `${hlColor}20` : C.border}`,
                    }}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        {(isWarn || isCritical) && <AlertTriangle size={13} color={hlColor!} />}
                        <span style={{ fontSize: 12, color: C.text1, fontWeight: 500 }}>{r.name}</span>
                      </div>
                      <div className="flex items-center gap-3 mt-1" style={{ fontSize: 10, color: C.text3 }}>
                        <span>当前: <span style={{ fontFamily: C.mono, color: hlColor ?? C.text1 }}>{r.current}</span></span>
                        <span>限额: <span style={{ fontFamily: C.mono }}>{r.limit}</span></span>
                      </div>
                    </div>
                    <div className="w-32">
                      <div className="h-2 rounded-full overflow-hidden" style={{ background: C.bg3 }}>
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: `${Math.min(r.usage, 100)}%`, background: usageColor(r.usage) }}
                        />
                      </div>
                    </div>
                    <span style={{ fontSize: 14, fontFamily: C.mono, fontWeight: 700, color: usageColor(r.usage), width: 40, textAlign: "right" }}>
                      {r.usage}%
                    </span>
                  </div>
                );
              })}
            </div>
          </Card>
        )}
      </div>
    </>
  );
}
