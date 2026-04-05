import { useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis,
  ResponsiveContainer, CartesianGrid, Tooltip,
  BarChart, Bar, Cell,
} from "recharts";
import { Card, CardHeader, ChartTooltip } from "@/components/shared";
import { C } from "@/theme";

export type NavChartPoint = { date: string; strategy: number; benchmark: number; excess: number };

export function EquityCurve({ navChartData }: { navChartData: NavChartPoint[] }) {
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
      <div className="px-4 pt-2 flex-1" style={{ minHeight: 220, minWidth: 0 }}>
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
            <YAxis tick={{ fill: C.text4, fontSize: 10 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} tickFormatter={(v: number) => v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : v.toFixed(0)} />
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
