/**
 * BacktestCompare.tsx — Wave 5 MVP 5.3 回测结果对比页 (sibling MVP 5.1/5.2 pattern).
 *
 * Multi-run comparison page with overlay charts + trade diff + reproducibility seal.
 * Supports up to 3 simultaneous runs side-by-side via URL ?runs=uuid1,uuid2,uuid3.
 *
 * Architecture (iter 205 design Option C Hybrid):
 * - Extended POST /api/backtest/compare (iter 206 PR #516 +5 fields)
 * - Parallel GET /api/backtest/{run_id}/nav for overlay charts
 * - Lazy GET /api/backtest/{run_id}/trades on expand for trade diff
 *
 * Design ref: docs/mvp/MVP_5_3_backtest_compare.md (iter 205)
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import {
  compareBacktests,
  getNavSeries,
  listBacktestHistory,
  type CompareRunSummary,
  type BacktestNavPoint,
} from "@/api/backtest";

const MAX_RUNS = 3;

// Distinct line colors for overlay charts (3-run max)
const RUN_COLORS = ["#22c55e", "#f59e0b", "#8b5cf6"] as const;

// ── S0 RunSelector ──────────────────────────────────────────────────────────

interface RunSelectorProps {
  selected: string[];
  onChange: (next: string[]) => void;
}

function RunSelector({ selected, onChange }: RunSelectorProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["backtest-compare", "history"],
    queryFn: () => listBacktestHistory(),
  });

  const completed = (data ?? []).filter((r) => r.status === "completed");

  function toggle(runId: string) {
    if (selected.includes(runId)) {
      onChange(selected.filter((id) => id !== runId));
    } else if (selected.length < MAX_RUNS) {
      onChange([...selected, runId]);
    }
  }

  return (
    <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-slate-100 mb-3">
        S0 — 选择对比 runs (最多 {MAX_RUNS} 个, 当前 {selected.length})
      </h2>
      {error ? (
        <div className="text-sm text-red-400">
          加载历史失败: {error instanceof Error ? error.message : "unknown"}
        </div>
      ) : isLoading ? (
        <div className="text-sm text-slate-500">加载中...</div>
      ) : completed.length === 0 ? (
        <div className="text-sm text-slate-500">无已完成回测记录</div>
      ) : (
        <div className="max-h-48 overflow-y-auto space-y-1 pr-2">
          {completed.slice(0, 50).map((r) => {
            const isOn = selected.includes(r.run_id);
            const atMax = selected.length >= MAX_RUNS && !isOn;
            return (
              <button
                key={r.run_id}
                onClick={() => toggle(r.run_id)}
                disabled={atMax}
                className={`w-full text-left text-xs p-2 rounded border transition-colors ${
                  isOn
                    ? "bg-sky-500/10 border-sky-500/40 text-sky-200"
                    : atMax
                      ? "bg-slate-950/40 border-slate-800 text-slate-600 cursor-not-allowed"
                      : "bg-slate-950/40 border-slate-800 text-slate-300 hover:bg-slate-950"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="flex-1 font-mono truncate">
                    {r.strategy_name || r.run_id.slice(0, 8)}
                  </span>
                  {r.sharpe != null && (
                    <span className="text-slate-400">
                      Sharpe={r.sharpe.toFixed(2)}
                    </span>
                  )}
                  {r.mdd != null && (
                    <span className="text-slate-400">
                      MDD={(r.mdd * 100).toFixed(1)}%
                    </span>
                  )}
                  <span className="text-slate-500 shrink-0">
                    {r.created_at?.slice(0, 10)}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── S1 MetricComparisonTable + S2 ReproducibilitySeal ──────────────────────

function MetricAndSealSection({ runs }: { runs: CompareRunSummary[] }) {
  if (runs.length === 0) {
    return (
      <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
        <div className="text-sm text-slate-500">选择至少 1 个 run 开始对比</div>
      </section>
    );
  }
  return (
    <>
      <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
        <h2 className="text-base font-semibold text-slate-100 mb-3">
          S1 — 指标对比
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-3">指标</th>
                {runs.map((r, i) => (
                  <th key={r.run_id} className="text-right py-2 pr-3">
                    <span style={{ color: RUN_COLORS[i] }}>●</span>{" "}
                    <span className="font-mono">{r.run_name || r.run_id.slice(0, 8)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <MetricRow label="Annual Return" runs={runs} pick={(r) => r.annual_return} pct />
              <MetricRow label="Sharpe" runs={runs} pick={(r) => r.sharpe_ratio} digits={3} />
              <MetricRow label="Sortino" runs={runs} pick={(r) => r.sortino_ratio} digits={3} />
              <MetricRow label="Max Drawdown" runs={runs} pick={(r) => r.max_drawdown} pct />
              <MetricRow label="Calmar" runs={runs} pick={(r) => r.calmar_ratio} digits={3} />
              <MetricRow label="Annual Turnover" runs={runs} pick={(r) => r.annual_turnover} digits={2} />
              <MetricRow label="Win Rate" runs={runs} pick={(r) => r.win_rate} pct />
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
        <h2 className="text-base font-semibold text-slate-100 mb-3">
          S2 — 复现性 seal (铁律 15)
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {runs.map((r, i) => (
            <div key={r.run_id} className="bg-slate-950/40 rounded p-3">
              <div className="flex items-center gap-2 mb-2">
                <span style={{ color: RUN_COLORS[i] }}>●</span>
                <span className="text-sm font-medium text-slate-200 font-mono truncate">
                  {r.run_name || r.run_id.slice(0, 8)}
                </span>
              </div>
              <SealField label="config_yaml_hash" value={r.config_yaml_hash} />
              <SealField label="git_commit" value={r.git_commit} />
              <SealField label="start_date" value={r.start_date} />
              <SealField label="end_date" value={r.end_date} />
              <SealField label="factors" value={r.factor_list.join(", ") || "—"} />
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function MetricRow({
  label,
  runs,
  pick,
  digits = 2,
  pct = false,
}: {
  label: string;
  runs: CompareRunSummary[];
  pick: (r: CompareRunSummary) => number | null;
  digits?: number;
  pct?: boolean;
}) {
  return (
    <tr className="border-b border-slate-800/50">
      <td className="py-2 pr-3 text-slate-400">{label}</td>
      {runs.map((r) => {
        const v = pick(r);
        const display =
          v == null ? "—" : pct ? `${(v * 100).toFixed(digits)}%` : v.toFixed(digits);
        return (
          <td key={r.run_id} className="py-2 pr-3 text-right text-slate-200">
            {display}
          </td>
        );
      })}
    </tr>
  );
}

function SealField({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="text-xs">
      <span className="text-slate-500">{label}:</span>{" "}
      <span className="text-slate-300 font-mono break-all">{value ?? "—"}</span>
    </div>
  );
}

// ── S3+S4 NavOverlay + DrawdownOverlay ─────────────────────────────────────

function NavDrawdownSection({ runIds, runs }: { runIds: string[]; runs: CompareRunSummary[] }) {
  // Parallel fetch via useQueries (avoid sequential waterfall)
  const navQueries = useQueries({
    queries: runIds.map((id) => ({
      queryKey: ["backtest-compare", "nav", id],
      queryFn: () => getNavSeries(id),
      staleTime: 5 * 60_000, // completed runs immutable, 5 min stale OK
    })),
  });

  const anyLoading = navQueries.some((q) => q.isLoading);
  const firstError = navQueries.find((q) => q.error)?.error;

  // Reviewer P1 iter 207: memoize navSeries with stable deps (navQueries.data refs
  // are reference-stable per TanStack Query when data unchanged). Without this,
  // .map(...) creates new array ref every render, defeating downstream useMemo.
  const navSeries: BacktestNavPoint[][] = useMemo(
    () => navQueries.map((q) => q.data ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [navQueries.map((q) => q.data).join("|")],
  );

  // Build ECharts option for NAV overlay (rebase 100)
  const navOption = useMemo(() => {
    const allDates = Array.from(
      new Set(navSeries.flatMap((s) => s.map((p) => p.trade_date))),
    ).sort();

    return {
      grid: { left: 60, right: 20, top: 30, bottom: 50 },
      xAxis: {
        type: "category",
        data: allDates,
        axisLabel: { color: "#94a3b8", fontSize: 10 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#94a3b8", fontSize: 10, formatter: "{value}" },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#cbd5e1", fontSize: 10 }, top: 0 },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 5 }],
      series: navSeries.map((points, i) => {
        const base = points[0]?.nav ?? 1;
        const data = allDates.map((d) => {
          const p = points.find((x) => x.trade_date === d);
          return p ? (p.nav / base) * 100 : null;
        });
        return {
          name: runs[i]?.run_name || runIds[i]?.slice(0, 8),
          type: "line",
          data,
          symbol: "none",
          // Reviewer P2 iter 207: modulo guards against future MAX_RUNS bump
          // without updating RUN_COLORS array.
          itemStyle: { color: RUN_COLORS[i % RUN_COLORS.length] },
          connectNulls: false,
        };
      }),
    };
  }, [navSeries, runs, runIds]);

  const drawdownOption = useMemo(() => {
    const allDates = Array.from(
      new Set(navSeries.flatMap((s) => s.map((p) => p.trade_date))),
    ).sort();

    return {
      grid: { left: 60, right: 20, top: 30, bottom: 50 },
      xAxis: {
        type: "category",
        data: allDates,
        axisLabel: { color: "#94a3b8", fontSize: 10 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#94a3b8", fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#cbd5e1", fontSize: 10 }, top: 0 },
      // Reviewer P3 iter 207: dataZoom sync with NAV chart for usability over
      // multi-year ranges (sibling NAV chart pattern).
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 5 }],
      series: navSeries.map((points, i) => {
        const data = allDates.map((d) => {
          const p = points.find((x) => x.trade_date === d);
          return p?.drawdown != null ? p.drawdown * 100 : null;
        });
        return {
          name: runs[i]?.run_name || runIds[i]?.slice(0, 8),
          type: "line",
          data,
          symbol: "none",
          areaStyle: { opacity: 0.2 },
          itemStyle: { color: RUN_COLORS[i % RUN_COLORS.length] },
          connectNulls: false,
        };
      }),
    };
  }, [navSeries, runs, runIds]);

  return (
    <>
      <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
        <h2 className="text-base font-semibold text-slate-100 mb-3">
          S3 — NAV 重基化曲线对比 (base=100)
        </h2>
        {firstError ? (
          <div className="text-sm text-red-400">
            NAV 加载失败: {firstError instanceof Error ? firstError.message : "unknown"}
          </div>
        ) : anyLoading ? (
          <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
            加载 NAV 中...
          </div>
        ) : (
          <ReactECharts
            option={navOption}
            style={{ height: "280px" }}
            opts={{ renderer: "canvas" }}
          />
        )}
      </section>

      <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
        <h2 className="text-base font-semibold text-slate-100 mb-3">
          S4 — 回撤曲线对比 (underwater)
        </h2>
        {firstError ? (
          <div className="text-sm text-red-400">
            回撤加载失败: {firstError instanceof Error ? firstError.message : "unknown"}
          </div>
        ) : anyLoading ? (
          <div className="h-32 flex items-center justify-center text-slate-500 text-sm">
            加载中...
          </div>
        ) : (
          <ReactECharts
            option={drawdownOption}
            style={{ height: "200px" }}
            opts={{ renderer: "canvas" }}
          />
        )}
      </section>
    </>
  );
}

// ── Page root ───────────────────────────────────────────────────────────────

export default function BacktestCompare() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialRuns = (searchParams.get("runs") || "")
    .split(",")
    .filter(Boolean)
    .slice(0, MAX_RUNS);
  const [selectedRuns, setSelectedRuns] = useState<string[]>(initialRuns);

  // Reviewer P3 iter 207: sync URL → state on browser back/forward navigation.
  // Without this useEffect, state stays stale relative to URL after history nav.
  const urlRunsStr = searchParams.get("runs") || "";
  useEffect(() => {
    const urlRuns = urlRunsStr.split(",").filter(Boolean).slice(0, MAX_RUNS);
    setSelectedRuns((prev) =>
      prev.join(",") === urlRuns.join(",") ? prev : urlRuns,
    );
  }, [urlRunsStr]);

  function updateRuns(next: string[]) {
    setSelectedRuns(next);
    if (next.length > 0) {
      setSearchParams({ runs: next.join(",") }, { replace: true });
    } else {
      setSearchParams({}, { replace: true });
    }
  }

  const compareQ = useQuery({
    queryKey: ["backtest-compare", "compare", selectedRuns.join(",")],
    queryFn: () => compareBacktests(selectedRuns),
    enabled: selectedRuns.length >= 2,
  });

  const runs = compareQ.data ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-slate-100">回测对比</h1>
        <p className="text-sm text-slate-400 mt-1">
          regression + WF + 实验多 run 对比 — Wave 5 MVP 5.3 (iter 207 蓝图实施)
        </p>
      </header>

      {compareQ.error && (
        <ErrorBanner
          message={`对比数据加载失败: ${compareQ.error instanceof Error ? compareQ.error.message : "unknown"}`}
        />
      )}

      <RunSelector selected={selectedRuns} onChange={updateRuns} />

      {selectedRuns.length < 2 ? (
        <section className="rounded-lg bg-slate-900/60 border border-slate-800 p-5">
          <div className="text-sm text-slate-500">
            请至少选择 2 个 run 进行对比 (当前 {selectedRuns.length}/{MAX_RUNS})
          </div>
        </section>
      ) : compareQ.isLoading ? (
        <PageSkeleton />
      ) : (
        <>
          <MetricAndSealSection runs={runs} />
          <NavDrawdownSection runIds={selectedRuns} runs={runs} />
        </>
      )}
    </div>
  );
}
