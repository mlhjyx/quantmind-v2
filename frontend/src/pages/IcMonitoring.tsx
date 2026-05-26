/**
 * IcMonitoring.tsx — Wave 5 MVP 5.2 IC 监控 + 因子衰减可视化 (sibling MVP 5.1 PtStatus).
 *
 * Pool-level monitoring dashboard answering 5 questions:
 *   S1: IC trend for factor X last 60/180/365d?
 *   S2: Which factors are decaying? (113-factor heatmap)
 *   S3: How many active/warning/retired?
 *   S4: CORE3+dv_ttm current state? (quick-access)
 *   S5: Which active factors have IC decay >50%? (alerts)
 *
 * Architecture: 1 new endpoint (ic-monitoring) + 3 existing reused
 * (factors/{name} time-series, factors/stats counts, factors/health alerts).
 *
 * Design ref: docs/mvp/MVP_5_2_ic_monitoring_decay.md (iter 201)
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import {
  fetchIcMonitoring,
  fetchFactorIcSeries,
  fetchFactorsStats,
  fetchFactorsHealth,
  type IcMonitoringFactor,
  type IcMonitoringResponse,
} from "@/api/factors";

// ── Status color helpers (sibling PtStatus.tsx pattern) ─────────────────────

function decayBadgeClasses(level: IcMonitoringFactor["decay_level"]): string {
  switch (level) {
    case "normal":
      return "bg-green-500/20 text-green-400 border border-green-500/30";
    case "warning":
      return "bg-amber-500/20 text-amber-400 border border-amber-500/30";
    case "critical":
      return "bg-red-500/20 text-red-400 border border-red-500/30";
    default:
      return "bg-slate-700/40 text-slate-400 border border-slate-700";
  }
}

function decayHexColor(level: IcMonitoringFactor["decay_level"]): string {
  switch (level) {
    case "normal":
      return "#22c55e";
    case "warning":
      return "#f59e0b";
    case "critical":
      return "#ef4444";
    default:
      // Reviewer P1 iter 203: exhaustive-default guard — backend may add new
      // decay_level union members (e.g. "retired"); falls through to grey here.
      // TS won't warn on union additions due to this default; add explicit cases
      // when backend extends contract.
      return "#475569";
  }
}

// ── S1 IcTimeSeriesSection ──────────────────────────────────────────────────

function IcTimeSeriesSection({ factors }: { factors: IcMonitoringFactor[] }) {
  const [selectedFactor, setSelectedFactor] = useState<string>(
    factors[0]?.name ?? "turnover_mean_20",
  );
  const [period, setPeriod] = useState<60 | 180 | 365>(180);

  const { data, isLoading, error } = useQuery({
    // Reviewer P2 iter 203: namespaced query key prevents future cross-page
    // cache collision (sibling EnvStateBanner shared-key pattern is intentional;
    // this is page-local).
    queryKey: ["ic-monitoring", "series", selectedFactor, period],
    queryFn: () => {
      const endDate = new Date().toISOString().slice(0, 10);
      const startDate = new Date(Date.now() - period * 86400 * 1000)
        .toISOString()
        .slice(0, 10);
      return fetchFactorIcSeries(selectedFactor, startDate, endDate);
    },
    enabled: !!selectedFactor,
  });

  const series = data?.ic_series ?? [];
  const option = {
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: "category",
      data: series.map((p) => p.trade_date),
      axisLabel: { color: "#94a3b8", fontSize: 10 },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#94a3b8", fontSize: 10, formatter: "{value}" },
      splitLine: { lineStyle: { color: "#1e293b" } },
    },
    tooltip: { trigger: "axis" },
    series: [
      {
        name: `${selectedFactor} IC`,
        type: "bar",
        data: series.map((p) => p.ic_value),
        itemStyle: {
          color: (params: { value: number }) =>
            params.value >= 0 ? "#22c55e" : "#ef4444",
        },
      },
    ],
  };

  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3 gap-3">
        <h2 className="text-base font-semibold text-slate-100">
          S1 — 因子 IC 时序
        </h2>
        <div className="flex items-center gap-2">
          <select
            value={selectedFactor}
            onChange={(e) => setSelectedFactor(e.target.value)}
            className="bg-slate-950 text-slate-200 text-xs px-2 py-1 rounded border border-slate-700"
          >
            {factors.map((f) => (
              <option key={f.name} value={f.name}>
                {f.name} {f.pool ? `(${f.pool})` : ""}
              </option>
            ))}
          </select>
          {[60, 180, 365].map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p as 60 | 180 | 365)}
              className={`text-xs px-2 py-1 rounded border ${
                period === p
                  ? "bg-sky-500/20 text-sky-300 border-sky-500/40"
                  : "bg-slate-950 text-slate-400 border-slate-700"
              }`}
            >
              {p}d
            </button>
          ))}
        </div>
      </div>
      {error ? (
        <div className="text-sm text-red-400">
          加载失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : isLoading ? (
        <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
          加载中...
        </div>
      ) : series.length === 0 ? (
        <div className="text-sm text-slate-500">无 IC 数据</div>
      ) : (
        <ReactECharts
          option={option}
          style={{ height: "240px" }}
          opts={{ renderer: "canvas" }}
        />
      )}
    </section>
  );
}

// ── S2 DecayHeatmapSection (Tailwind grid, ECharts overkill for color cells) ─

function DecayHeatmapSection({ data }: { data: IcMonitoringResponse | undefined }) {
  const factors = data?.decay_heatmap ?? [];
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S2 — 因子衰减 heatmap ({factors.length} 个因子)
      </h2>
      {factors.length === 0 ? (
        <div className="text-sm text-slate-500">无因子数据</div>
      ) : (
        <>
          <div className="grid grid-cols-8 md:grid-cols-12 gap-1.5">
            {factors.map((f) => (
              <div
                key={f.name}
                title={`${f.name}\n池: ${f.pool ?? "-"}\nIC ma20: ${f.ic_ma20?.toFixed(4) ?? "-"}\nDecay: ${f.decay_level ?? "n/a"}`}
                className="aspect-square rounded text-[8px] text-white/80 flex items-center justify-center p-0.5 text-center break-all leading-tight cursor-help"
                style={{ backgroundColor: decayHexColor(f.decay_level) }}
              >
                {f.name.slice(0, 8)}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3 mt-3 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: "#22c55e" }} />
              normal
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: "#f59e0b" }} />
              warning
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: "#ef4444" }} />
              critical
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: "#475569" }} />
              n/a
            </span>
          </div>
        </>
      )}
    </section>
  );
}

// ── S3 FactorHealthSummary ──────────────────────────────────────────────────

function FactorHealthSummary() {
  // Reviewer P1+P2 iter 203: destructure `error` for fail-loud per 铁律 33 +
  // namespace query key under "ic-monitoring".
  const { data, error } = useQuery({
    queryKey: ["ic-monitoring", "factors-stats"],
    queryFn: fetchFactorsStats,
    refetchInterval: 60_000,
  });
  const items = [
    { label: "Active", value: data?.active ?? "—", color: "text-green-400" },
    { label: "Warning", value: data?.warning ?? "—", color: "text-amber-400" },
    { label: "Critical", value: data?.critical ?? "—", color: "text-red-400" },
    { label: "Retired", value: data?.retired ?? "—", color: "text-slate-400" },
  ];
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S3 — 因子健康总览
      </h2>
      {error ? (
        <div className="text-sm text-red-400 mb-3">
          加载失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : null}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {items.map((it) => (
          <div key={it.label} className="bg-slate-950/40 rounded p-3">
            <div className="text-xs text-slate-500">{it.label}</div>
            <div className={`text-2xl font-bold mt-1 ${it.color}`}>{it.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── S4 CoreFactorPanel ──────────────────────────────────────────────────────

function CoreFactorPanel({ coreFactors }: { coreFactors: IcMonitoringFactor[] }) {
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S4 — CORE 因子 (PT 生产配置)
      </h2>
      {coreFactors.length === 0 ? (
        <div className="text-sm text-slate-500">无 CORE 因子数据</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {coreFactors.map((f) => (
            <Link
              key={f.name}
              to={`/factors/${f.name}`}
              className="bg-slate-950/40 rounded p-3 hover:bg-slate-950/70 transition-colors"
            >
              <div className="text-xs text-slate-500 font-mono">{f.name}</div>
              <div className="text-lg font-bold text-slate-100 mt-1">
                {f.ic_ma20?.toFixed(4) ?? "—"}
              </div>
              <div className="text-xs text-slate-500 mb-2">IC ma20</div>
              <span
                className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${decayBadgeClasses(f.decay_level)}`}
              >
                {f.decay_level ?? "n/a"}
              </span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

// ── S5 DecayAlertTable ──────────────────────────────────────────────────────

function DecayAlertTable() {
  // Reviewer P1+P2 iter 203: destructure `error` for fail-loud per 铁律 33 +
  // namespace query key under "ic-monitoring".
  const { data, error } = useQuery({
    queryKey: ["ic-monitoring", "factors-health"],
    queryFn: fetchFactorsHealth,
    refetchInterval: 60_000,
  });
  const alerts = (data?.factors ?? []).filter((f) => f.decay_warning);
  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S5 — 衰减告警 ({alerts.length} 个)
      </h2>
      {error ? (
        <div className="text-sm text-red-400 mb-3">
          加载失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : null}
      {alerts.length === 0 ? (
        <div className="text-sm text-slate-500">
          ✓ 无衰减告警 (所有 active 因子 IC 比 ≥ 0.5)
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-3">因子</th>
                <th className="text-right py-2 pr-3">IC 30d</th>
                <th className="text-right py-2 pr-3">IC 90d</th>
                <th className="text-left py-2 pr-3">趋势</th>
                <th className="text-left py-2">详情</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((f) => (
                <tr key={f.name} className="border-b border-slate-800/50">
                  <td className="py-2 pr-3 text-slate-200 font-mono">{f.name}</td>
                  <td className="py-2 pr-3 text-right text-slate-300">
                    {f.ic_mean_30d?.toFixed(4) ?? "—"}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-300">
                    {f.ic_mean_90d?.toFixed(4) ?? "—"}
                  </td>
                  <td className="py-2 pr-3 text-amber-400">{f.ic_trend}</td>
                  <td className="py-2">
                    <Link to={`/factors/${f.name}`} className="text-sky-400 hover:underline">
                      查看 →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Page root ───────────────────────────────────────────────────────────────

export default function IcMonitoring() {
  const monitorQ = useQuery({
    // Reviewer P3 iter 203: refetchInterval=60s consistent with S3/S5
    // subordinate queries — primary heatmap data should not go stale.
    queryKey: ["ic-monitoring", "root"],
    queryFn: () => fetchIcMonitoring(),
    refetchInterval: 60_000,
  });

  if (monitorQ.isLoading && !monitorQ.data) {
    return <PageSkeleton />;
  }

  const monitorData = monitorQ.data;
  const heatmapFactors = monitorData?.decay_heatmap ?? [];
  const coreFactors = monitorData?.core_factors ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-100">IC 监控</h1>
        <p className="text-sm text-slate-400 mt-1">
          因子衰减可视化 — Wave 5 MVP 5.2 (iter 203 蓝图实施)
        </p>
      </header>

      {monitorQ.error && (
        <ErrorBanner
          message={`IC 监控数据加载失败: ${monitorQ.error instanceof Error ? monitorQ.error.message : "unknown"}`}
        />
      )}

      <IcTimeSeriesSection factors={heatmapFactors} />
      <DecayHeatmapSection data={monitorData} />
      <FactorHealthSummary />
      <CoreFactorPanel coreFactors={coreFactors} />
      <DecayAlertTable />
    </div>
  );
}
