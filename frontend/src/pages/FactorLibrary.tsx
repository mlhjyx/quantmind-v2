import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import FactorTable from "@/components/factor/FactorTable";
import HealthPanel from "@/components/factor/HealthPanel";
import CorrelationHeatmap from "@/components/factor/CorrelationHeatmap";
import {
  getFactorLibrary,
  getFactorLibraryStats,
  getFactorCorrelation,
  getFactorICTrends,
  triggerHealthCheck,
  triggerCorrelationPrune,
} from "@/api/factors";
import type { FactorSummary, FactorCorrelationMatrix } from "@/api/factors";
import { STALE } from "@/api/QueryProvider";
import { ErrorBanner } from "@/components/ui/ErrorBanner";

const EMPTY_STATS = { active: 0, new: 0, degraded: 0, retired: 0 };

const STATUS_STAT_COLORS: Record<string, string> = {
  active:   "text-green-400",
  new:      "text-blue-400",
  degraded: "text-yellow-400",
  retired:  "text-red-400",
};

type ActivePanel = "table" | "health" | "correlation";

export default function FactorLibrary() {
  const [activePanel, setActivePanel] = useState<ActivePanel>("table");
  const [healthCheckLoading, setHealthCheckLoading] = useState(false);
  const [pruneLoading, setPruneLoading] = useState(false);

  const { data: factors = [], isLoading: factorsLoading, isError: factorsError } = useQuery({
    queryKey: ["factor-library"],
    queryFn: getFactorLibrary,
    staleTime: STALE.factor,
    retry: 1,
  });

  const { data: stats = EMPTY_STATS } = useQuery({
    queryKey: ["factor-library-stats"],
    queryFn: getFactorLibraryStats,
    staleTime: STALE.factor,
    retry: 1,
  });

  const EMPTY_CORR: FactorCorrelationMatrix = { factors: [], matrix: [] };
  const { data: correlation = EMPTY_CORR, isLoading: corrLoading } = useQuery({
    queryKey: ["factor-correlation"],
    queryFn: getFactorCorrelation,
    staleTime: STALE.factor,
    retry: 1,
    enabled: activePanel === "correlation",
  });

  const { data: icTrends = [], isLoading: trendsLoading } = useQuery({
    queryKey: ["factor-ic-trends"],
    queryFn: getFactorICTrends,
    staleTime: STALE.factor,
    retry: 1,
    enabled: activePanel === "health",
  });

  async function handleHealthCheck() {
    setHealthCheckLoading(true);
    try { await triggerHealthCheck(); } catch { /* fallback ok */ }
    setHealthCheckLoading(false);
  }

  async function handleCorrelationPrune() {
    setPruneLoading(true);
    try { await triggerCorrelationPrune(); } catch { /* fallback ok */ }
    setPruneLoading(false);
  }

  const statCards = [
    { key: "active",   label: "活跃",  value: stats.active },
    { key: "new",      label: "新入库", value: stats.new },
    { key: "degraded", label: "衰退",  value: stats.degraded },
    { key: "retired",  label: "淘汰",  value: stats.retired },
  ];

  const panels: { key: ActivePanel; label: string }[] = [
    { key: "table",       label: "因子表格" },
    { key: "health",      label: "健康度面板" },
    { key: "correlation", label: "相关性矩阵" },
  ];

  return (
    <div>
      <Breadcrumb items={[{ label: "因子库" }]} />

      {/* API error banner */}
      {factorsError && (
        <ErrorBanner message="因子数据加载失败，请确认后端API已启动" className="mb-4" />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">因子库</h1>
          <p className="text-sm text-slate-400 mt-0.5">管理活跃因子 · 监控健康度 · 控制相关性</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            loading={healthCheckLoading}
            onClick={handleHealthCheck}
          >
            因子体检
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={pruneLoading}
            onClick={handleCorrelationPrune}
          >
            相关性裁剪
          </Button>
          <Button variant="secondary" size="sm">导出</Button>
          <Button size="sm">+ 添加</Button>
        </div>
      </div>

      {/* Top stats */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {statCards.map((s) => (
          <GlassCard key={s.key} padding="sm">
            <p className="text-xs text-slate-400 mb-1">{s.label}因子</p>
            <p className={`text-3xl font-bold tabular-nums ${STATUS_STAT_COLORS[s.key]}`}>
              {s.value}
            </p>
          </GlassCard>
        ))}
      </div>

      {/* Panel tabs */}
      <div className="flex gap-1 mb-4 border-b border-slate-800">
        {panels.map((p) => (
          <button
            key={p.key}
            onClick={() => setActivePanel(p.key)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activePanel === p.key
                ? "text-blue-400 border-blue-400"
                : "text-slate-400 border-transparent hover:text-slate-200"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Panel content */}
      {activePanel === "table" && (
        <GlassCard>
          {factorsLoading ? (
            <div className="py-20 text-center text-slate-500 text-sm">加载中...</div>
          ) : (
            <FactorTable factors={factors as FactorSummary[]} />
          )}
        </GlassCard>
      )}

      {activePanel === "health" && (
        <HealthPanel
          stats={stats}
          icTrends={icTrends}
          loading={trendsLoading}
        />
      )}

      {activePanel === "correlation" && (
        <CorrelationHeatmap
          data={correlation}
          loading={corrLoading}
        />
      )}
    </div>
  );
}
