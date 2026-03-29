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

// ── Mock fallback data (kept as default values) ──
const MOCK_VAR_DATA: VarPoint[] = Array.from({ length: 60 }, (_, i) => ({
  date: `${Math.floor(i / 2) + 1}/${(i % 2) * 15 + 1}`,
  var95: +(2.0 + Math.sin(i * 0.1) * 0.8 + (i % 7) * 0.04).toFixed(2),
  var99: +(3.0 + Math.sin(i * 0.1) * 1.2 + (i % 5) * 0.05).toFixed(2),
  limit: 3.0,
}));

const MOCK_EXPOSURE: ExposureItem[] = [
  { factor: "市场Beta", exposure: 0.72,  limit: 1.0, color: C.accent },
  { factor: "规模",     exposure: -0.35, limit: 0.5, color: "#818cf8" },
  { factor: "价值",     exposure: 0.28,  limit: 0.5, color: "#f59e0b" },
  { factor: "动量",     exposure: 0.45,  limit: 0.6, color: C.up },
  { factor: "波动率",   exposure: -0.18, limit: 0.3, color: C.down },
  { factor: "流动性",   exposure: 0.12,  limit: 0.4, color: "#60a5fa" },
];

const MOCK_STRESS: StressTest[] = [
  { scenario: "2015股灾",      impact: -18.5, probability: "低",  recovery: "45天" },
  { scenario: "2020疫情",      impact: -12.3, probability: "低",  recovery: "30天" },
  { scenario: "利率上行100bp", impact: -5.8,  probability: "中",  recovery: "15天" },
  { scenario: "行业集中风险",  impact: -8.2,  probability: "中",  recovery: "20天" },
  { scenario: "流动性枯竭",    impact: -15.6, probability: "极低", recovery: "60天" },
  { scenario: "北向大幅流出",  impact: -6.4,  probability: "中高", recovery: "10天" },
];

const MOCK_LIMITS: RiskLimit[] = [
  { name: "单只持仓上限", current: "7.8%",  limit: "8%",   usage: 97,  status: "warn" },
  { name: "行业集中度",   current: "18.2%", limit: "25%",  usage: 73,  status: "ok" },
  { name: "95% VaR",     current: "2.8%",  limit: "3.0%", usage: 93,  status: "warn" },
  { name: "最大回撤",     current: "4.32%", limit: "10%",  usage: 43,  status: "ok" },
  { name: "Beta暴露",     current: "0.72",  limit: "1.0",  usage: 72,  status: "ok" },
  { name: "换手率(月)",   current: "120%",  limit: "200%", usage: 60,  status: "ok" },
  { name: "相关性(基准)", current: "0.65",  limit: "0.9",  usage: 72,  status: "ok" },
  { name: "杠杆率",       current: "1.0x",  limit: "1.0x", usage: 100, status: "critical" },
];

const MOCK_OVERVIEW_METRICS: OverviewMetric[] = [
  { label: "95% VaR",  value: "2.8%",   color: C.warn },
  { label: "99% CVaR", value: "4.1%",   color: C.down },
  { label: "Beta",     value: "0.72",   color: C.text1 },
  { label: "年化波动", value: "12.8%",  color: C.text1 },
  { label: "最大回撤", value: "-4.32%", color: C.down },
  { label: "活跃预警", value: "2",      color: C.warn },
];

function usageColor(usage: number) {
  if (usage >= 90) return C.down;
  if (usage >= 70) return C.warn;
  return C.up;
}

export default function RiskManagement() {
  const [tab, setTab] = useState("风控总览");

  const [overviewMetrics, setOverviewMetrics] = useState<OverviewMetric[]>(MOCK_OVERVIEW_METRICS);
  const [varData, setVarData]                 = useState<VarPoint[]>(MOCK_VAR_DATA);
  const [exposure, setExposure]               = useState<ExposureItem[]>(MOCK_EXPOSURE);
  const [stressTests, setStressTests]         = useState<StressTest[]>(MOCK_STRESS);
  const [riskLimits, setRiskLimits]           = useState<RiskLimit[]>(MOCK_LIMITS);
  const [loading, setLoading]                 = useState(true);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const [overview, limits, stress] = await Promise.allSettled([
          axios.get<{ metrics?: OverviewMetric[]; var_series?: VarPoint[]; exposure?: ExposureItem[] }>("/api/risk/overview"),
          axios.get<RiskLimit[]>("/api/risk/limits"),
          axios.get<StressTest[]>("/api/risk/stress-tests"),
        ]);
        if (!live) return;
        if (overview.status === "fulfilled") {
          const d = overview.value.data;
          if (d.metrics)    setOverviewMetrics(d.metrics);
          if (d.var_series) setVarData(d.var_series);
          if (d.exposure)   setExposure(d.exposure);
        }
        if (limits.status === "fulfilled") setRiskLimits(limits.value.data);
        if (stress.status === "fulfilled") setStressTests(stress.value.data);
      } finally {
        if (live) setLoading(false);
      }
    };
    void load();
    return () => { live = false; };
  }, []);

  const warnCount     = riskLimits.filter((r) => r.status === "warn").length;
  const criticalCount = riskLimits.filter((r) => r.status === "critical").length;
  const okCount       = riskLimits.filter((r) => r.status === "ok").length;

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
        {tab === "风控总览" && (
          <>
            <div className="grid grid-cols-6 gap-3">
              {overviewMetrics.map((m) => (
                <Card key={m.label} className="px-3.5 py-2.5">
                  <div style={{ fontSize: 9, color: C.text4 }}>{m.label}</div>
                  {loading
                    ? <div className="h-5 w-16 rounded animate-pulse mt-1" style={{ background: C.bg3 }} />
                    : <div style={{ fontSize: 16, fontFamily: C.mono, fontWeight: 700, color: m.color ?? C.text1 }}>{m.value}</div>
                  }
                </Card>
              ))}
            </div>

            <div className="grid grid-cols-12 gap-3">
              <Card className="col-span-8 flex flex-col overflow-hidden">
                <CardHeader title="VaR走势" titleEn="Value at Risk" />
                <div className="px-4 pt-2 flex-1" style={{ minHeight: 240 }}>
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
                </div>
              </Card>

              <Card className="col-span-4">
                <CardHeader title="因子暴露" titleEn="Factor Exposure" />
                <div className="p-3 space-y-2.5">
                  {exposure.map((e) => (
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
              {riskLimits.map((r) => {
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
