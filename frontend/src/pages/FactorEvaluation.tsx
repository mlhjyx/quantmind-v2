import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { MetricCard } from "@/components/ui/MetricCard";
import TabICAnalysis from "@/components/factor/evaluation/TabICAnalysis";
import TabGroupReturns from "@/components/factor/evaluation/TabGroupReturns";
import TabICDecay from "@/components/factor/evaluation/TabICDecay";
import TabCorrelation from "@/components/factor/evaluation/TabCorrelation";
import TabAnnual from "@/components/factor/evaluation/TabAnnual";
import TabRegimeStats from "@/components/factor/evaluation/TabRegimeStats";
import { getFactorReport } from "@/api/factors";
import { STALE } from "@/api/QueryProvider";

type TabKey = "ic" | "groups" | "decay" | "correlation" | "annual" | "regime";

const TABS: { key: TabKey; label: string }[] = [
  { key: "ic",          label: "IC分析" },
  { key: "groups",      label: "分组收益" },
  { key: "decay",       label: "IC衰减" },
  { key: "correlation", label: "相关性" },
  { key: "annual",      label: "分年度" },
  { key: "regime",      label: "分市场状态" },
];

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  active:   { label: "✅ 活跃",  cls: "bg-green-500/15 text-green-400 border-green-500/30" },
  new:      { label: "🆕 新入库", cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  degraded: { label: "⚠️ 衰退",  cls: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
  retired:  { label: "❌ 淘汰",  cls: "bg-red-500/15 text-red-400 border-red-500/30" },
};

export default function FactorEvaluation() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<TabKey>("ic");

  const factorId = id ?? "turnover_mean_20";

  const { data: report, isLoading, isError } = useQuery({
    queryKey: ["factor-report", factorId],
    queryFn: () => getFactorReport(factorId),
    staleTime: STALE.factor,
    retry: 1,
  });

  const badge = report ? (STATUS_BADGE[report.status] ?? { label: report.status, cls: "bg-slate-500/15 text-slate-400 border-slate-500/30" }) : null;

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "因子库", path: "/factors" },
          { label: report ? `${report.name} 评估报告` : "因子评估报告" },
        ]}
      />

      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-bold text-white font-mono">
              {report?.name ?? factorId}
            </h1>
            {badge && (
              <span className={`px-2.5 py-0.5 rounded-full text-xs border ${badge.cls}`}>
                {badge.label}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-400">
            {report && (
              <>
                <span>类别: {report.category}</span>
                <span>来源: {report.source}</span>
                <span>推荐频率: {report.recommended_freq}</span>
                <span>方向: {report.direction === 1 ? "正向" : "负向"}</span>
                {report.description && (
                  <span className="text-slate-500 max-w-sm truncate">{report.description}</span>
                )}
              </>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">编辑重评</Button>
          <Button variant="secondary" size="sm">添加到策略</Button>
          <Button variant="secondary" size="sm">导出PDF</Button>
          <Button variant="danger" size="sm">✗ 丢弃</Button>
          <Button size="sm">✓ 入库</Button>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[0, 1, 2, 3].map((i) => (
            <GlassCard key={i} className="h-20 animate-pulse bg-slate-800/40">{null}</GlassCard>
          ))}
        </div>
      )}

      {/* Error state */}
      {isError && (
        <GlassCard className="mb-5 py-8 text-center">
          <p className="text-red-400 text-sm">加载因子报告失败</p>
        </GlassCard>
      )}

      {/* Top metrics */}
      {report && (
        <>
          <div className="grid grid-cols-4 gap-3 mb-5">
            <MetricCard
              label="IC均值"
              value={report.ic_mean.toFixed(4)}
              status={Math.abs(report.ic_mean) >= 0.03 ? "good" : Math.abs(report.ic_mean) >= 0.02 ? "warning" : "alert"}
            />
            <MetricCard
              label="IC_IR"
              value={report.ic_ir.toFixed(3)}
              status={report.ic_ir >= 0.5 ? "good" : report.ic_ir >= 0.3 ? "warning" : "alert"}
            />
            <MetricCard
              label="t值 (Newey-West)"
              value={`${report.t_stat.toFixed(2)} / ${report.newey_west_t.toFixed(2)}`}
              status={report.t_stat >= 2.5 ? "good" : report.t_stat >= 2.0 ? "warning" : "alert"}
            />
            <MetricCard
              label="Gate得分"
              value={report.gate_score}
              status={report.gate_score >= 75 ? "good" : report.gate_score >= 60 ? "warning" : "alert"}
            />
          </div>

          <div className="grid grid-cols-4 gap-3 mb-5">
            <MetricCard
              label="FDR校正t值"
              value={report.fdr_t_stat.toFixed(3)}
              status={report.fdr_t_stat >= 2.0 ? "good" : "warning"}
              subtitle={report.fdr_t_stat < 2.0 ? "FDR校正后<2.0 ⚠️" : undefined}
            />
            <MetricCard
              label="IC半衰期"
              value={`${report.half_life_days} 日`}
              status="normal"
            />
            <MetricCard
              label="覆盖率"
              value={`${(report.coverage * 100).toFixed(1)}%`}
              status={report.coverage >= 0.9 ? "good" : "warning"}
            />
            <MetricCard
              label="推荐调仓频率"
              value={report.recommended_freq}
              status="normal"
            />
          </div>

          {/* Tabs */}
          <div className="flex gap-1 mb-4 border-b border-slate-800">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                  activeTab === t.key
                    ? "text-blue-400 border-blue-400"
                    : "text-slate-400 border-transparent hover:text-slate-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {activeTab === "ic" && <TabICAnalysis report={report} />}
          {activeTab === "groups" && <TabGroupReturns report={report} />}
          {activeTab === "decay" && <TabICDecay report={report} />}
          {activeTab === "correlation" && <TabCorrelation report={report} />}
          {activeTab === "annual" && <TabAnnual report={report} />}
          {activeTab === "regime" && <TabRegimeStats report={report} />}
        </>
      )}
    </div>
  );
}
