import { useEffect, useState } from "react";
import axios from "axios";
import { Shield, AlertTriangle } from "lucide-react";
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

// ── Types ──
interface OverviewMetric { label: string; value: string; color?: string; }
interface RiskLimit      { name: string; current: string; limit: string; usage: number; status: string; }
interface StressTest     { scenario: string; impact: number; probability: string; recovery: string; }
interface VarPoint       { date: string; var95: number; var99: number; limit: number; }
interface ExposureItem   { factor: string; exposure: number; limit: number; color: string; }


function usageColor(usage: number) {
  if (usage >= 90) return C.down;
  if (usage >= 70) return C.warn;
  return C.up;
}

export default function RiskManagement() {
  const [tab, setTab] = useState("风控总览");

  const [overviewMetrics, setOverviewMetrics] = useState<OverviewMetric[] | null>(null);
  const [varData, setVarData]                 = useState<VarPoint[] | null>(null);
  const [exposure, setExposure]               = useState<ExposureItem[] | null>(null);
  const [stressTests, setStressTests]         = useState<StressTest[] | null>(null);
  const [riskLimits, setRiskLimits]           = useState<RiskLimit[] | null>(null);
  const [loading, setLoading]                 = useState(true);
  const [fetchError, setFetchError]           = useState(false);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        // 先请求live数据，如果为空fallback到paper
        let mode = "live";
        const [overview, limits, stress] = await Promise.allSettled([
          axios.get<{ metrics?: OverviewMetric[]; var_series?: VarPoint[]; exposure?: ExposureItem[] }>("/api/risk/overview", { params: { execution_mode: mode } }),
          axios.get<RiskLimit[]>("/api/risk/limits", { params: { execution_mode: mode } }),
          axios.get<StressTest[]>("/api/risk/stress-tests", { params: { execution_mode: mode } }),
        ]);
        if (!live) return;

        // 检查live数据是否足够
        const liveMetrics = overview.status === "fulfilled" ? overview.value.data.metrics : undefined;
        const liveEmpty = !liveMetrics || liveMetrics.length === 0;

        // 如果live数据不足，fallback到paper
        if (liveEmpty && mode === "live") {
          mode = "paper";
          const [ov2, li2, st2] = await Promise.allSettled([
            axios.get<{ metrics?: OverviewMetric[]; var_series?: VarPoint[]; exposure?: ExposureItem[] }>("/api/risk/overview", { params: { execution_mode: mode } }),
            axios.get<RiskLimit[]>("/api/risk/limits", { params: { execution_mode: mode } }),
            axios.get<StressTest[]>("/api/risk/stress-tests", { params: { execution_mode: mode } }),
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
    const id = setInterval(() => void load(), 30_000);
    return () => { live = false; clearInterval(id); };
  }, []);

  const warnCount     = riskLimits?.filter((r) => r.status === "warn").length ?? 0;
  const criticalCount = riskLimits?.filter((r) => r.status === "critical").length ?? 0;
  const okCount       = riskLimits?.filter((r) => r.status === "ok").length ?? 0;

  return (
    <>
      <PageHeader title="风控管理" titleEn="Risk Management">
        <TabButtons tabs={["风控总览", "压力测试", "限额监控"]} active={tab} onChange={setTab} />
        <div
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg"
          style={{ background: `${C.up}10`, border: `1px solid ${C.up}30` }}
        >
          <Shield size={14} color={C.up} />
          <span style={{ fontSize: 11, color: C.up, fontWeight: 500 }}>风险等级: LOW</span>
        </div>
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
