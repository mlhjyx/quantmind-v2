import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import {
  AreaChart, Area, XAxis, YAxis,
  ResponsiveContainer, CartesianGrid, Tooltip,
  BarChart, Bar, Cell,
} from "recharts";
import { ChevronRight, Clock, Play, Bell } from "lucide-react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { fetchSummary, fetchPositions, fetchNAVSeries } from "@/api/dashboard";
import type { DashboardSummary, Position } from "@/types/dashboard";
import { C } from "@/theme";

type FactorRow = { name: string; cat: string; ic: number; ir: number; dir: string; status: string; trend: number[] };
type PipelineStep = { name: string; status: string };
type Alert = { level: string; color: string; title: string; desc: string; time: string };


// ── Sparkline SVG component ──
function Sparkline({ data, color, width = 52, height = 22 }: { data: number[]; color: string; width?: number; height?: number }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * (height - 2) - 1}`).join(" ");
  const fillPoints = `0,${height} ${points} ${width},${height}`;
  const gradId = `sp-${color.replace('#', '')}`;
  return (
    <svg width={width} height={height} className="shrink-0">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.25} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={fillPoints} fill={`url(#${gradId})`} />
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Card / CardHeader primitives (token-aligned) ──
function Card({ children, className = "", style = {} }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={`rounded-xl ${className}`} style={{ background: C.bg1, border: `1px solid ${C.border}`, ...style }}>
      {children}
    </div>
  );
}

function CardHeader({ title, titleEn, right }: { title: string; titleEn?: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between px-4 py-2" style={{ borderBottom: `1px solid ${C.border}` }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: C.text1 }}>
        {title}{titleEn && <span style={{ color: C.text4, fontWeight: 400, fontSize: 11 }}> {titleEn}</span>}
      </span>
      {right}
    </div>
  );
}

// ── Chart tooltip ──
function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: C.bg2, border: `1px solid ${C.borderLight}`, boxShadow: "0 8px 32px rgba(0,0,0,0.4)" }}>
      <div style={{ fontSize: 10, color: C.text3, marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2" style={{ fontSize: 11 }}>
          <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span style={{ color: C.text2 }}>{p.name}: </span>
          <span style={{ color: C.text1, fontFamily: C.mono, fontWeight: 600 }}>
            {typeof p.value === "number" ? p.value.toFixed(4) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Row 1: 8 KPI cards ──
interface KPICard {
  label: string; en: string; value: string; sub?: string;
  valueC?: string; subC?: string; spark?: number[]; sparkC?: string; accent?: boolean;
}

function KPIGrid({ summary }: { summary: DashboardSummary | null }) {
  const nav    = summary?.nav ?? 1.2854;
  const cumRet = summary?.cumulative_return ?? 0.2854;
  const dayRet = summary?.daily_return ?? 0.0097;
  const sharpe = summary?.sharpe ?? 1.87;
  const mdd    = summary?.mdd ?? -0.0432;

  const cards: KPICard[] = [
    {
      label: "总权益", en: "EQUITY",
      value: `¥${nav.toLocaleString("zh", { maximumFractionDigits: 0 })}`,
      sub: `${cumRet >= 0 ? "+" : ""}${(cumRet * 100).toFixed(2)}%`,
      subC: cumRet >= 0 ? C.up : C.down,
      sparkC: C.up, accent: true,
    },
    {
      label: "今日P&L", en: "TODAY",
      value: `${dayRet >= 0 ? "+" : ""}¥${Math.abs(dayRet * nav).toFixed(0)}`,
      valueC: dayRet >= 0 ? C.up : C.down,
      sub: `${dayRet >= 0 ? "+" : ""}${(dayRet * 100).toFixed(2)}%`,
      subC: dayRet >= 0 ? C.up : C.down,
      sparkC: dayRet >= 0 ? C.up : C.down,
    },
    {
      label: "年化收益", en: "CAGR",
      value: "—", valueC: C.up,
      sub: "—", subC: C.up,
    },
    {
      label: "Sharpe", en: "DSR✓",
      value: sharpe.toFixed(2),
      sub: "—", subC: C.text3,
    },
    {
      label: "最大回撤", en: "MDD",
      value: `${(mdd * 100).toFixed(2)}%`, valueC: C.down,
      sub: "—", subC: C.down,
    },
    {
      label: "胜率", en: "Win%",
      value: "—",
      sub: "—", subC: C.text3,
    },
    {
      label: "仓位", en: "POS",
      value: summary ? `${(100 - (summary.cash_ratio ?? 0) * 100).toFixed(1)}%` : "—",
      sub: summary ? `${summary.position_count ?? 0}只持仓` : "—", subC: C.text3,
    },
    {
      label: "风险", en: "RISK",
      value: "LOW", valueC: C.up,
      sub: "—", subC: C.warn,
    },
  ];

  return (
    <div className="grid grid-cols-4 gap-3">
      {cards.map((m, i) => (
        <Card key={i} className="p-3.5 flex flex-col justify-between overflow-hidden" style={{
          minHeight: 92,
          ...(m.accent ? { borderColor: `${C.accent}25`, background: `linear-gradient(135deg, ${C.bg1}, ${C.accent}06)` } : {}),
        }}>
          <div className="flex items-center justify-between">
            <span style={{ fontSize: 11, color: C.text3 }}>{m.label}</span>
            <span style={{ fontSize: 9, color: C.text4 }}>{m.en}</span>
          </div>
          <div className="flex items-end justify-between mt-auto gap-1">
            <div className="min-w-0">
              <div style={{
                fontSize: 20, fontWeight: 700, color: m.valueC ?? C.text1, fontFamily: C.mono, lineHeight: 1.1,
                ...(m.valueC ? { textShadow: `0 0 16px ${m.valueC}30` } : {}),
              }}>{m.value}</div>
              {m.sub && (
                <span className="block truncate" style={{ fontSize: 10, color: m.subC ?? C.text3, marginTop: 2 }}>
                  {m.sub}
                </span>
              )}
            </div>
            {m.spark && <Sparkline data={m.spark} color={m.sparkC ?? C.accent} width={48} height={22} />}
          </div>
        </Card>
      ))}
    </div>
  );
}

// ── Row 2a: Equity curve with time selector ──
type NavChartPoint = { date: string; strategy: number; benchmark: number; excess: number };
function EquityCurve({ navChartData }: { navChartData: NavChartPoint[] }) {
  const [period, setPeriod] = useState("1Y");

  return (
    <Card className="col-span-8 flex flex-col overflow-hidden">
      <CardHeader
        title="净值曲线" titleEn="Equity Curve"
        right={
          <div className="flex items-center gap-0.5">
            {["1M", "3M", "1Y", "ALL"].map((t) => (
              <button
                key={t} onClick={() => setPeriod(t)}
                className="px-2.5 py-1 rounded-md cursor-pointer transition-colors"
                style={{ fontSize: 11, color: t === period ? "#fff" : C.text4, background: t === period ? C.accent : "transparent" }}
              >{t}</button>
            ))}
          </div>
        }
      />
      <div className="px-4 pt-2 flex-1" style={{ minHeight: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={navChartData} margin={{ top: 8, right: 15, bottom: 0, left: -10 }}>
            <defs>
              <linearGradient id="gStrat" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor="#7c5cfc" stopOpacity={0.25} />
                <stop offset="50%"  stopColor="#7c5cfc" stopOpacity={0.06} />
                <stop offset="100%" stopColor="#7c5cfc" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gBench" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor="#3e4158" stopOpacity={0.06} />
                <stop offset="100%" stopColor="#3e4158" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="stratStroke" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%"   stopColor="#7c5cfc" />
                <stop offset="50%"  stopColor="#00f0ff" />
                <stop offset="100%" stopColor="#00e5a0" />
              </linearGradient>
              <filter id="glow">
                <feGaussianBlur stdDeviation="2.5" result="coloredBlur" />
                <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>
            <CartesianGrid stroke={`${C.border}60`} strokeDasharray="2 6" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: C.text4, fontSize: 10 }} axisLine={false} tickLine={false} interval={14} />
            <YAxis tick={{ fill: C.text4, fontSize: 10 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(2)} />
            <Tooltip content={<ChartTooltip />} />
            <Area name="策略"  type="monotone" dataKey="strategy"  stroke="url(#stratStroke)" strokeWidth={2} fill="url(#gStrat)"  filter="url(#glow)" dot={false} />
            <Area name="基准"  type="monotone" dataKey="benchmark" stroke="#6b70a0"            strokeWidth={1} fill="url(#gBench)"  strokeDasharray="4 3" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {/* Excess bar */}
      <div className="px-4" style={{ height: 44 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={navChartData} margin={{ top: 2, right: 15, bottom: 0, left: -10 }}>
            <XAxis dataKey="date" tick={false} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: C.text4, fontSize: 9 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`} />
            <Tooltip content={<ChartTooltip />} />
            <Bar name="超额%" dataKey="excess" radius={[1, 1, 0, 0]}>
              {navChartData.map((d, i) => (
                <Cell key={i} fill={d.excess >= 0 ? `${C.up}50` : `${C.down}50`} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* Legend */}
      <div className="flex items-center gap-5 px-4 pb-2" style={{ fontSize: 10 }}>
        <span className="flex items-center gap-1.5">
          <span className="w-6 h-[2px]" style={{ background: "linear-gradient(90deg, #7c5cfc, #00f0ff, #00e5a0)" }} />
          <span style={{ color: C.text3 }}>策略</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-6" style={{ borderTop: "2px dashed #6b70a0" }} />
          <span style={{ color: C.text3 }}>基准</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-2 rounded-sm" style={{ background: `${C.up}60` }} />
          <span style={{ color: C.text3 }}>超额</span>
        </span>
      </div>
    </Card>
  );
}

// ── Row 2b: Alerts + Strategies ──
function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  return (
    <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 320 }}>
      <CardHeader
        title="预警" titleEn="Alerts"
        right={
          <span className="w-5 h-5 rounded-full flex items-center justify-center" style={{ fontSize: 10, color: "#fff", background: C.down, fontWeight: 600 }}>
            {alerts.length}
          </span>
        }
      />
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {alerts.slice(0, 20).map((a, i) => (
          <div key={i} className="rounded-lg px-3 py-2.5 cursor-pointer" style={{ background: `${a.color}06`, border: `1px solid ${a.color}15` }}>
            <div className="flex items-center gap-2">
              <span className="shrink-0 px-1.5 py-0.5 rounded" style={{ fontSize: 9, color: a.color, fontWeight: 700, fontFamily: C.mono, background: `${a.color}12` }}>
                {a.level}
              </span>
              <span style={{ fontSize: 12, color: C.text1, fontWeight: 500 }}>{a.title}</span>
              <span className="ml-auto shrink-0" style={{ fontSize: 10, color: C.text4 }}>{a.time}</span>
            </div>
            <div style={{ fontSize: 11, color: C.text3, marginTop: 3, paddingLeft: 30 }}>{a.desc}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function StrategiesPanel() {
  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="策略" titleEn="Strategies"
        right={<span style={{ fontSize: 10, color: C.text4 }}><Clock size={11} className="inline mr-1" />调仓 03-24</span>}
      />
      <div className="p-3 space-y-2">
        {[
          { name: "多因子选股 Alpha-V3", sub: "A股·30只", pnl: "+0.82%", sharpe: "1.87", up: true,  active: true },
          { name: "CTA趋势跟踪",         sub: "A股·5只",  pnl: "-0.34%", sharpe: "0.95", up: false, active: true },
          { name: "外汇 EUR/USD",        sub: "Phase 2",  pnl: "—",      sharpe: "—",    up: false, active: false },
        ].map((s, i) => (
          <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer" style={{ background: C.bg2, opacity: s.active ? 1 : 0.35 }}>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ background: s.active ? (s.up ? C.up : C.down) : C.text4 }} />
              <span style={{ fontSize: 12, color: C.text1 }}>{s.name}</span>
              <span style={{ fontSize: 10, color: C.text4 }}>{s.sub}</span>
            </div>
            <div className="flex items-center gap-3">
              <span style={{ fontSize: 10, color: C.text4 }}>SR {s.sharpe}</span>
              <span style={{ fontSize: 15, fontFamily: C.mono, fontWeight: 700, color: s.pnl.startsWith("+") ? C.up : s.pnl.startsWith("-") ? C.down : C.text4 }}>
                {s.pnl}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Row 3a: Holdings table ──
function HoldingsTable({ positions }: { positions: Position[] }) {
  const rows = positions;

  return (
    <Card className="col-span-4">
      <CardHeader
        title="持仓明细" titleEn="Holdings"
        right={<span style={{ fontSize: 10, color: C.text4 }}>30只 · 85.5%</span>}
      />
      <div className="px-3 pb-2">
        <table className="w-full" style={{ fontSize: 11 }}>
          <thead>
            <tr style={{ color: C.text4 }}>
              <th className="text-left py-1.5 font-normal">代码</th>
              <th className="text-right py-1.5 font-normal">权重</th>
              <th className="text-right py-1.5 font-normal">盈亏</th>
              <th className="text-right py-1.5 font-normal">天</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const wt  = p.weight * 100;
              const pnl = p.unrealized_pnl * 100;
              return (
                <tr key={p.code} className="cursor-pointer" style={{ borderTop: `1px solid ${C.border}` }}>
                  <td className="py-1.5" style={{ color: C.text2, fontFamily: C.mono }}>{p.code}</td>
                  <td className="text-right py-1.5">
                    <div className="flex items-center justify-end gap-1">
                      <div className="h-1 rounded-full" style={{ width: wt * 4, background: C.accent, opacity: 0.5 }} />
                      <span style={{ fontFamily: C.mono, color: C.text2 }}>{wt.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="text-right py-1.5" style={{ fontFamily: C.mono, color: pnl >= 0 ? C.up : C.down }}>
                    {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%
                  </td>
                  <td className="text-right py-1.5" style={{ color: C.text4, fontFamily: C.mono }}>{p.holding_days}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Row 3b: Monthly returns heatmap ──
function MonthlyHeatmap({ monthlyData }: { monthlyData: Record<string, number[]> }) {
  return (
    <Card className="col-span-4">
      <CardHeader title="月度收益" titleEn="Monthly %" />
      <div className="px-3 pb-3 pt-1.5">
        <div className="flex gap-[3px] mb-[3px]">
          <div style={{ width: 28 }} />
          {Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="flex-1 text-center" style={{ fontSize: 9, color: C.text4 }}>{i + 1}</div>
          ))}
          <div className="text-center" style={{ width: 40, fontSize: 9, color: C.text4, fontWeight: 600 }}>YTD</div>
        </div>
        {Object.entries(monthlyData).map(([year, vals]) => {
          const safeVals = vals.map(v => v ?? 0);
          const ytd = safeVals.filter(v => v !== 0).reduce((a, b) => a + b, 0);
          return (
            <div key={year} className="flex gap-[3px] mb-[3px]">
              <div style={{ width: 28, fontSize: 11, color: C.text3, lineHeight: "30px", fontWeight: 500 }}>{year.slice(2)}</div>
              {safeVals.map((v, i) => {
                const isEmpty = year === "2026" && i >= 3;
                if (isEmpty) return <div key={i} className="flex-1 rounded" style={{ height: 30, background: C.bg2 }} />;
                const intensity = Math.min(Math.abs(v) / 5, 1);
                const bgColor = v >= 0 ? C.up : C.down;
                return (
                  <div key={i} className="flex-1 rounded flex items-center justify-center cursor-pointer"
                    style={{
                      height: 30,
                      background: `${bgColor}${Math.round(intensity * 40 + 10).toString(16).padStart(2, "0")}`,
                      fontSize: 10, color: v >= 0 ? C.up : C.down, fontFamily: C.mono,
                    }}>
                    {v !== 0 ? v.toFixed(1) : ""}
                  </div>
                );
              })}
              <div className="rounded flex items-center justify-center" style={{
                height: 30, width: 40,
                background: ytd >= 0 ? `${C.up}20` : `${C.down}20`,
                fontSize: 11, color: ytd >= 0 ? C.up : C.down, fontWeight: 700, fontFamily: C.mono,
              }}>
                {ytd.toFixed(1)}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

type IndustryItem = { name: string; pct: number; color: string };

// ── Row 3c: Industry distribution + system status ──
function IndustryAndSystem({ industryDist }: { industryDist: IndustryItem[] }) {
  return (
    <div className="col-span-4 flex flex-col gap-3">
      <Card className="flex-1">
        <CardHeader title="行业分布" titleEn="Industry" />
        <div className="px-3 pb-2.5 pt-1.5 space-y-2">
          {industryDist.map((ind) => (
            <div key={ind.name} className="flex items-center gap-2.5">
              <span className="shrink-0" style={{ fontSize: 11, color: C.text2, width: 52 }}>{ind.name}</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: C.bg2 }}>
                <div className="h-full rounded-full" style={{ width: `${(ind.pct / 30) * 100}%`, background: ind.color, opacity: 0.75 }} />
              </div>
              <span style={{ fontSize: 10, color: C.text3, fontFamily: C.mono, width: 32, textAlign: "right" }}>{ind.pct}%</span>
            </div>
          ))}
        </div>
      </Card>
      <Card className="p-3">
        <div className="grid grid-cols-3 gap-2">
          {[
            { l: "PG",       ok: true },
            { l: "Redis",    ok: true },
            { l: "Celery",   ok: true },
            { l: "Tushare",  ok: true },
            { l: "DeepSeek", ok: true, s: "¥87" },
            { l: "数据",     ok: true, s: "2m" },
          ].map((s, i) => (
            <div key={i} className="flex items-center gap-1.5 px-2 py-1.5 rounded-md" style={{ background: C.bg2 }}>
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.ok ? C.up : C.down }} />
              <span style={{ fontSize: 10, color: C.text2 }}>{s.l}</span>
              {s.s && <span className="ml-auto" style={{ fontSize: 9, color: C.text4, fontFamily: C.mono }}>{s.s}</span>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ── Row 4a: Factor library table ──
function FactorLibraryPanel({ factorData }: { factorData: FactorRow[] }) {
  const activeCount = factorData.filter((f) => f.status === "active").length;
  const newCount = factorData.filter((f) => f.status === "new").length;
  const decayCount = factorData.filter((f) => f.status === "decay").length;
  return (
    <Card className="col-span-7">
      <CardHeader
        title="因子库" titleEn="Factor Library"
        right={
          <div className="flex items-center gap-3" style={{ fontSize: 10 }}>
            <span style={{ color: C.up }}>● {activeCount} 活跃</span>
            <span style={{ color: C.accent }}>● {newCount} 新入</span>
            <span style={{ color: C.warn }}>● {decayCount} 衰退</span>
          </div>
        }
      />
      <div className="px-3 pb-2">
        <table className="w-full" style={{ fontSize: 11 }}>
          <thead>
            <tr style={{ color: C.text4 }}>
              <th className="text-left py-1.5 font-normal">因子名</th>
              <th className="text-left py-1.5 font-normal">类别</th>
              <th className="text-right py-1.5 font-normal">IC</th>
              <th className="text-right py-1.5 font-normal">IR</th>
              <th className="text-center py-1.5 font-normal">方向</th>
              <th className="text-center py-1.5 font-normal">趋势</th>
              <th className="text-center py-1.5 font-normal">状态</th>
            </tr>
          </thead>
          <tbody>
            {factorData.map((f) => (
              <tr key={f.name} className="cursor-pointer" style={{ borderTop: `1px solid ${C.border}` }}>
                <td className="py-1.5" style={{ color: C.text2, fontFamily: C.mono }}>{f.name}</td>
                <td className="py-1.5">
                  <span className="px-1.5 py-0.5 rounded" style={{ fontSize: 10, color: C.text3, background: C.bg2 }}>{f.cat}</span>
                </td>
                <td className="text-right py-1.5" style={{ fontFamily: C.mono, fontWeight: 600, color: Math.abs(f.ic) < 0.02 ? C.text4 : f.ic > 0 ? C.up : "#f59e0b" }}>
                  {f.ic > 0 ? "+" : ""}{f.ic.toFixed(3)}
                </td>
                <td className="text-right py-1.5" style={{ fontFamily: C.mono, color: C.text2 }}>{f.ir.toFixed(2)}</td>
                <td className="text-center py-1.5">
                  <span className="px-1.5 py-0.5 rounded" style={{
                    fontSize: 9, fontWeight: 500,
                    color: f.dir === "正向" ? C.up : "#f59e0b",
                    background: f.dir === "正向" ? `${C.up}10` : "#f59e0b10",
                  }}>
                    {f.dir === "正向" ? "↑ 正向" : "↓ 反向"}
                  </span>
                </td>
                <td className="text-center py-1.5">
                  <div className="flex justify-center">
                    <Sparkline data={f.trend} color={f.status === "decay" ? C.warn : C.accent} width={44} height={16} />
                  </div>
                </td>
                <td className="text-center py-1.5">
                  <span className="px-1.5 py-0.5 rounded-full" style={{
                    fontSize: 9,
                    color:      f.status === "active" ? C.up : f.status === "new" ? C.accent : C.warn,
                    background: f.status === "active" ? `${C.up}10` : f.status === "new" ? C.accentSoft : `${C.warn}10`,
                  }}>
                    {f.status === "active" ? "Active" : f.status === "new" ? "New" : "Decay"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Row 4b: AI Pipeline ──
function AIPipelinePanel({ pipelineSteps }: { pipelineSteps: PipelineStep[] }) {
  return (
    <Card className="col-span-5">
      <CardHeader
        title="AI 闭环" titleEn="Pipeline"
        right={
          <span className="px-2 py-0.5 rounded-full" style={{ fontSize: 9, color: "#a5b4fc", background: C.accentSoft, fontWeight: 500 }}>
            L1 半自动
          </span>
        }
      />
      <div className="p-3.5 space-y-3">
        {/* Pipeline steps */}
        <div className="flex items-center gap-[2px]">
          {pipelineSteps.map((s, i) => (
            <div key={i} className="flex items-center">
              <div className="px-2 py-1.5 rounded-md text-center shrink-0" style={{
                fontSize: 10, minWidth: 40,
                color:      s.status === "done" ? C.up : s.status === "running" ? "#fff" : C.text4,
                background: s.status === "done" ? `${C.up}12` : s.status === "running" ? C.accent : C.bg2,
                fontWeight: s.status === "running" ? 600 : 400,
                ...(s.status === "running" ? { boxShadow: `0 0 10px ${C.accent}40` } : {}),
              }}>{s.name}</div>
              {i < pipelineSteps.length - 1 && <ChevronRight size={10} color={C.text4} className="shrink-0 mx-[-1px]" />}
            </div>
          ))}
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-4 gap-2">
          {[
            { l: "上次运行", v: "2h前" },
            { l: "下次调度", v: "03-24" },
            { l: "GP代数",   v: "47" },
            { l: "候选因子", v: "2" },
          ].map((s, i) => (
            <div key={i} className="rounded-lg p-2" style={{ background: C.bg2 }}>
              <div style={{ fontSize: 9, color: C.text4 }}>{s.l}</div>
              <div style={{ fontSize: 12, color: C.text2, fontFamily: C.mono, fontWeight: 500 }}>{s.v}</div>
            </div>
          ))}
        </div>

        {/* Pending approval */}
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <span style={{ fontSize: 11, color: C.text2, fontWeight: 500 }}>待审批</span>
            <span className="w-4 h-4 rounded-full flex items-center justify-center" style={{ background: `${C.warn}15`, fontSize: 9, color: C.warn, fontWeight: 600 }}>2</span>
          </div>
          {[
            { name: "vol_skew_20",  ic: "0.031", ir: "0.72", src: "GP" },
            { name: "cond_vol_mom", ic: "0.028", ir: "0.61", src: "LLM" },
          ].map((f, i) => (
            <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg mb-1.5" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
              <div>
                <div style={{ fontSize: 11, color: C.text2, fontFamily: C.mono }}>{f.name}</div>
                <div style={{ fontSize: 9, color: C.text4 }}>IC {f.ic} · IR {f.ir} · {f.src}</div>
              </div>
              <div className="flex gap-1.5">
                <button className="px-2 py-1 rounded-md cursor-pointer" style={{ fontSize: 10, background: `${C.up}12`, color: C.up, fontWeight: 500 }}>批准</button>
                <button className="px-2 py-1 rounded-md cursor-pointer" style={{ fontSize: 10, background: `${C.down}12`, color: C.down, fontWeight: 500 }}>拒绝</button>
              </div>
            </div>
          ))}
        </div>

        {/* Quick actions */}
        <div className="flex gap-2 flex-wrap">
          {[
            { l: "▶ 运行回测", c: C.accent },
            { l: "因子体检",   c: C.up },
            { l: "导出报告",   c: C.text3 },
            { l: "风控检查",   c: C.warn },
          ].map((a) => (
            <button key={a.l} className="px-2.5 py-1.5 rounded-lg cursor-pointer" style={{ fontSize: 10, color: a.c, background: `${a.c}08`, border: `1px solid ${a.c}20` }}>
              {a.l}
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}

// ── Main page ──
export default function DashboardOverview() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [monthlyData, setMonthlyData] = useState<Record<string, number[]> | null>(null);
  const [industryDist, setIndustryDist] = useState<IndustryItem[] | null>(null);
  const [navChartData, setNavChartData] = useState<NavChartPoint[]>([]);
  const [factorData, setFactorData] = useState<FactorRow[]>([]);
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [monthlyError, setMonthlyError] = useState<string | null>(null);
  const [industryError, setIndustryError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, p] = await Promise.all([
        fetchSummary(),
        fetchPositions(),
      ]);
      setSummary(s);
      setPositions(p);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "加载失败";
      setError(`核心数据加载失败: ${msg}`);
    } finally {
      setLoading(false);
    }

    // Alerts
    setAlertsError(null);
    axios.get<Alert[]>("/api/dashboard/alerts")
      .then((r) => setAlerts(r.data))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setAlertsError(`预警数据加载失败: ${msg}`);
        setAlerts([]);
      });

    // Monthly returns
    setMonthlyError(null);
    axios.get<Record<string, number[]>>("/api/dashboard/monthly-returns")
      .then((r) => setMonthlyData(r.data))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setMonthlyError(`月度收益加载失败: ${msg}`);
        setMonthlyData({});
      });

    // Industry distribution
    setIndustryError(null);
    axios.get<IndustryItem[]>("/api/dashboard/industry-distribution")
      .then((r) => setIndustryDist(r.data))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setIndustryError(`行业分布加载失败: ${msg}`);
        setIndustryDist([]);
      });

    // NAV series → transform to chart format
    fetchNAVSeries("all")
      .then((pts) => {
        const chartPts = pts.map((pt) => ({
          date: pt.trade_date.slice(5),  // "MM-DD"
          strategy: pt.nav,
          benchmark: 1.0,               // benchmark not in API; keep flat
          excess: +(pt.cumulative_return * 100).toFixed(2),
        }));
        setNavChartData(chartPts);
      })
      .catch(() => {
        setNavChartData([]);
      });

    // Factors list
    axios.get<{ name: string; category: string; direction: string; status: string; ic_mean: number | null; ic_ir: number | null }[]>("/api/factors")
      .then((r) => {
        const rows: FactorRow[] = r.data.map((f) => ({
          name: f.name,
          cat: f.category ?? "未知",
          ic: f.ic_mean ?? 0,
          ir: f.ic_ir ?? 0,
          dir: f.direction === "positive" ? "正向" : "反向",
          status: f.status === "active" ? "active" : f.status === "candidate" ? "new" : "decay",
          trend: [],
        }));
        setFactorData(rows);
      })
      .catch(() => {
        setFactorData([]);
      });

    // Pipeline status → transform node_statuses to steps array
    axios.get<{ node_statuses: Record<string, string>; current_node: string | null; status: string }>("/api/pipeline/status")
      .then((r) => {
        const nodeMap = r.data.node_statuses ?? {};
        const currentNode = r.data.current_node;
        const pipelineStatus = r.data.status;
        const steps: PipelineStep[] = Object.entries(nodeMap).map(([name, st]) => {
          let status: string;
          if (st === "completed") status = "done";
          else if (name === currentNode && pipelineStatus === "running") status = "running";
          else if (st === "pending") status = "pending";
          else status = st;
          return { name, status };
        });
        setPipelineSteps(steps);
      })
      .catch(() => {
        setPipelineSteps([]);
      });
  }, []);

  useEffect(() => { void loadData(); }, [loadData]);

  return (
    <div style={{ background: C.bg0, minHeight: "100vh", fontFamily: "'Inter', -apple-system, 'Noto Sans SC', sans-serif" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-2.5 shrink-0" style={{ borderBottom: `1px solid ${C.border}` }}>
        <Breadcrumb />
        <div className="flex items-center gap-3">
          <h1 style={{ fontSize: 18, fontWeight: 700, color: C.text1 }}>驾驶舱</h1>
          <span className="px-2 py-0.5 rounded-full" style={{ fontSize: 10, background: `${C.up}15`, color: C.up, fontWeight: 500 }}>● 模拟盘</span>
          <span style={{ fontSize: 12, color: C.text4 }}>
            {summary?.trade_date ? `v1.1 · ${summary.trade_date}` : "动量反转 v3 · A股"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative w-8 h-8 rounded-lg flex items-center justify-center cursor-pointer" style={{ background: C.bg1, border: `1px solid ${C.border}` }}>
            <Bell size={15} color={C.text3} />
            <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center" style={{ background: C.down, fontSize: 9, color: "#fff", fontWeight: 600 }}>
              {alerts?.length ?? 0}
            </div>
          </div>
          <button
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg cursor-pointer"
            style={{ background: C.accentSoft, border: `1px solid ${C.accent}40` }}
            onClick={() => void loadData()}
          >
            <Play size={12} color={C.accent} fill={C.accent} />
            <span style={{ fontSize: 12, color: "#a5b4fc" }}>{loading ? "加载中..." : "运行回测"}</span>
          </button>
          <Button variant="secondary" size="sm" onClick={() => void loadData()}>
            {loading ? "..." : "刷新"}
          </Button>
        </div>
      </div>

      {/* Error banners */}
      {error && (
        <div className="px-5 pt-3">
          <ErrorBanner message={error} onRetry={() => void loadData()} />
        </div>
      )}
      {alertsError && (
        <div className="px-5 pt-2">
          <ErrorBanner message={alertsError} onRetry={() => void loadData()} />
        </div>
      )}
      {monthlyError && (
        <div className="px-5 pt-2">
          <ErrorBanner message={monthlyError} onRetry={() => void loadData()} />
        </div>
      )}
      {industryError && (
        <div className="px-5 pt-2">
          <ErrorBanner message={industryError} onRetry={() => void loadData()} />
        </div>
      )}

      {/* Sub-market nav links */}
      <div className="flex items-center gap-3 px-5 py-2" style={{ borderBottom: `1px solid ${C.border}` }}>
        <Link to="/dashboard/astock" className="flex items-center gap-2 px-3 py-1.5 rounded-lg cursor-pointer" style={{ background: C.bg1, border: `1px solid ${C.border}` }}>
          <span style={{ fontSize: 12, color: C.text1 }}>A股策略 v1.1</span>
          <span style={{ fontSize: 10, color: C.text4 }}>PT Day 3/60</span>
          <ChevronRight size={12} color={C.text4} />
        </Link>
        <Link to="/dashboard/forex" className="flex items-center gap-2 px-3 py-1.5 rounded-lg cursor-pointer" style={{ background: C.bg1, border: `1px solid ${C.border}`, opacity: 0.5 }}>
          <span style={{ fontSize: 12, color: C.text3 }}>外汇策略</span>
          <span style={{ fontSize: 10, color: C.text4 }}>Phase 2</span>
          <ChevronRight size={12} color={C.text4} />
        </Link>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3 pt-3">
        {/* ROW 1: 2×4 KPI cards */}
        {loading ? (
          <div className="grid grid-cols-4 gap-3">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="rounded-xl p-3.5" style={{ minHeight: 92, background: C.bg1, border: `1px solid ${C.border}` }}>
                <div className="h-3 w-16 rounded mb-2 animate-pulse" style={{ background: C.bg3 }} />
                <div className="h-6 w-24 rounded animate-pulse" style={{ background: C.bg3 }} />
              </div>
            ))}
          </div>
        ) : (
          <KPIGrid summary={summary} />
        )}

        {/* ROW 2: Equity curve (8 cols) + Alerts+Strategies (4 cols) */}
        <div className="grid grid-cols-12 gap-3">
          <EquityCurve navChartData={navChartData} />
          <div className="col-span-4 flex flex-col gap-3">
            {alerts === null ? (
              <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 320 }}>
                <div className="p-4 space-y-2">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="h-12 rounded-lg animate-pulse" style={{ background: C.bg2 }} />
                  ))}
                </div>
              </Card>
            ) : (
              <AlertsPanel alerts={alerts} />
            )}
            <StrategiesPanel />
          </div>
        </div>

        {/* ROW 3: Holdings (4) + Monthly heatmap (4) + Industry+System (4) */}
        <div className="grid grid-cols-12 gap-3">
          <HoldingsTable positions={positions} />
          {monthlyData === null ? (
            <Card className="col-span-4">
              <CardHeader title="月度收益" titleEn="Monthly %" />
              <div className="p-3 space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-8 rounded animate-pulse" style={{ background: C.bg2 }} />
                ))}
              </div>
            </Card>
          ) : (
            <MonthlyHeatmap monthlyData={monthlyData} />
          )}
          {industryDist === null ? (
            <div className="col-span-4 flex flex-col gap-3">
              <Card className="flex-1">
                <CardHeader title="行业分布" titleEn="Industry" />
                <div className="p-3 space-y-2">
                  {[...Array(6)].map((_, i) => (
                    <div key={i} className="h-5 rounded animate-pulse" style={{ background: C.bg2 }} />
                  ))}
                </div>
              </Card>
            </div>
          ) : (
            <IndustryAndSystem industryDist={industryDist} />
          )}
        </div>

        {/* ROW 4: Factor library (7) + AI Pipeline (5) */}
        <div className="grid grid-cols-12 gap-3">
          <FactorLibraryPanel factorData={factorData} />
          <AIPipelinePanel pipelineSteps={pipelineSteps} />
        </div>
      </div>
    </div>
  );
}
