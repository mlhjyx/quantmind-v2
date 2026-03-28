import { useState } from "react";
import { useNavigate } from "react-router-dom";
import NAVChart from "@/components/NAVChart";
import type { NAVPoint, NAVPeriod } from "@/types/dashboard";
import { MOCK_NAV_SERIES } from "@/api/mock";

// ── Types ──────────────────────────────────────────────────────────────────

interface GraduationMetric {
  id: string;
  name: string;
  current: number | string;
  target: string;
  /** "pass" | "warn" | "fail" | "observe" */
  status: "pass" | "warn" | "fail" | "observe";
  /** 0-100, used for progress bar */
  progress: number;
  unit?: string;
  description?: string;
}

interface GraduationData {
  pt_day: number;
  pt_total_days: number;
  overall_status: "on_track" | "at_risk" | "failing";
  metrics: GraduationMetric[];
}

// ── Mock data ──────────────────────────────────────────────────────────────

const MOCK_GRADUATION: GraduationData = {
  pt_day: 3,
  pt_total_days: 60,
  overall_status: "on_track",
  metrics: [
    {
      id: "sharpe",
      name: "Sharpe Ratio",
      current: 1.12,
      target: "≥ 0.72",
      status: "pass",
      progress: 100,
      description: "基线 1.03",
    },
    {
      id: "mdd",
      name: "最大回撤",
      current: -12.3,
      target: "< 35%",
      status: "pass",
      progress: 100,
      unit: "%",
      description: "基线 -39.7%",
    },
    {
      id: "slippage",
      name: "滑点偏差",
      current: 38,
      target: "< 50%",
      status: "pass",
      progress: 76,
      unit: "%",
      description: "实盘成本/回测成本",
    },
    {
      id: "signal_consistency",
      name: "信号一致性",
      current: 91,
      target: "≥ 80%",
      status: "pass",
      progress: 100,
      unit: "%",
      description: "实盘信号 vs 回测信号重合率",
    },
    {
      id: "data_latency",
      name: "数据延迟",
      current: 1.2,
      target: "< 2 分钟",
      status: "pass",
      progress: 100,
      unit: "min",
      description: "行情数据到因子计算延迟",
    },
    {
      id: "system_stability",
      name: "系统稳定性",
      current: 100,
      target: "≥ 99%",
      status: "pass",
      progress: 100,
      unit: "%",
      description: "无崩溃运行天数/总天数",
    },
    {
      id: "rebalance_exec",
      name: "调仓执行率",
      current: 100,
      target: "≥ 90%",
      status: "pass",
      progress: 100,
      unit: "%",
      description: "成功执行的调仓次数/计划次数",
    },
    {
      id: "factor_ic",
      name: "因子有效性 IC",
      current: "全部 > 0",
      target: "5因子 IC > 0",
      status: "pass",
      progress: 100,
      description: "turnover/volatility/reversal/amihud/bp_ratio",
    },
    {
      id: "nav_trend",
      name: "净值趋势",
      current: "观察中",
      target: "60日净值向上",
      status: "observe",
      progress: 5,
      description: "Day 3，数据积累中，主观判断",
    },
  ],
};

// ── Helpers ────────────────────────────────────────────────────────────────

function statusColor(status: GraduationMetric["status"]) {
  switch (status) {
    case "pass":
      return {
        badge: "bg-green-500/20 text-green-400 border-green-500/30",
        bar: "bg-green-500",
        card: "border-green-500/20",
        icon: "✅",
      };
    case "warn":
      return {
        badge: "bg-amber-500/20 text-amber-400 border-amber-500/30",
        bar: "bg-amber-500",
        card: "border-amber-500/20",
        icon: "⚠️",
      };
    case "fail":
      return {
        badge: "bg-red-500/20 text-red-400 border-red-500/30",
        bar: "bg-red-500",
        card: "border-red-500/30",
        icon: "❌",
      };
    case "observe":
      return {
        badge: "bg-sky-500/20 text-sky-400 border-sky-500/30",
        bar: "bg-sky-500",
        card: "border-sky-500/20",
        icon: "👁️",
      };
  }
}

function overallBadge(status: GraduationData["overall_status"]) {
  switch (status) {
    case "on_track":
      return "bg-green-500/20 text-green-400 border border-green-500/30";
    case "at_risk":
      return "bg-amber-500/20 text-amber-400 border border-amber-500/30";
    case "failing":
      return "bg-red-500/20 text-red-400 border border-red-500/30";
  }
}

function overallLabel(status: GraduationData["overall_status"]) {
  switch (status) {
    case "on_track":
      return "进展顺利";
    case "at_risk":
      return "存在风险";
    case "failing":
      return "未达标";
  }
}

function formatValue(m: GraduationMetric): string {
  if (typeof m.current === "string") return m.current;
  if (m.id === "mdd") return `${m.current}%`;
  if (m.unit) return `${m.current}${m.unit}`;
  return String(m.current);
}

// ── MetricCard ─────────────────────────────────────────────────────────────

function MetricCard({ metric }: { metric: GraduationMetric }) {
  const colors = statusColor(metric.status);

  return (
    <div
      className={[
        "rounded-xl border bg-white/5 backdrop-blur-md p-4",
        colors.card,
      ].join(" ")}
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <p className="text-xs text-gray-400">{metric.name}</p>
          <p className="text-lg font-bold text-white mt-0.5">
            {formatValue(metric)}
          </p>
        </div>
        <span className="text-lg" title={metric.status}>
          {colors.icon}
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1.5 bg-white/10 rounded-full mb-2">
        <div
          className={`h-full rounded-full transition-all duration-500 ${colors.bar}`}
          style={{ width: `${Math.min(metric.progress, 100)}%` }}
        />
      </div>

      <div className="flex items-center justify-between">
        <p className="text-[10px] text-gray-500 truncate">
          {metric.description}
        </p>
        <span
          className={`ml-2 shrink-0 text-[10px] px-1.5 py-0.5 rounded border ${colors.badge}`}
        >
          {metric.target}
        </span>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function PTGraduation() {
  const navigate = useNavigate();
  const [navPeriod, setNavPeriod] = useState<NAVPeriod>("all");
  const data = MOCK_GRADUATION;
  const navData: NAVPoint[] = MOCK_NAV_SERIES;

  const passCount = data.metrics.filter((m) => m.status === "pass").length;
  const totalCount = data.metrics.length;
  const canApply = data.pt_day >= 55;
  const progressPct = Math.round((data.pt_day / data.pt_total_days) * 100);

  return (
    <div className="min-h-screen bg-[#0f172a] text-white p-4 lg:p-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-100">PT 毕业评估</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            v1.1 · 5因子等权 Top15 月度 · 毕业标准: Sharpe≥0.72 / MDD&lt;35% /
            滑点偏差&lt;50%
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Pass count */}
          <span className="text-xs text-gray-400">
            <span className="text-green-400 font-bold">{passCount}</span> /{" "}
            {totalCount} 达标
          </span>

          {/* Overall badge */}
          <span
            className={`px-3 py-1 rounded-full text-xs font-medium ${overallBadge(data.overall_status)}`}
          >
            {overallLabel(data.overall_status)}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-6 rounded-xl border border-white/10 bg-white/5 backdrop-blur-md p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-300">
            Paper Trading 进度
          </span>
          <span className="text-sm font-bold text-white">
            Day{" "}
            <span className="text-blue-400">{data.pt_day}</span>{" "}
            / {data.pt_total_days}
          </span>
        </div>
        <div className="w-full h-3 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full transition-all duration-700"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <div className="flex justify-between mt-1">
          <span className="text-[10px] text-gray-500">开始</span>
          <span className="text-[10px] text-gray-500">
            {progressPct}% 完成 · 还剩 {data.pt_total_days - data.pt_day} 天
          </span>
          <span className="text-[10px] text-gray-500">Day 60</span>
        </div>
      </div>

      {/* Metrics grid 3×3 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {data.metrics.map((m) => (
          <MetricCard key={m.id} metric={m} />
        ))}
      </div>

      {/* NAV chart */}
      <div className="mb-6">
        <NAVChart
          data={navData}
          period={navPeriod}
          onPeriodChange={setNavPeriod}
          loading={false}
        />
      </div>

      {/* Footer: advice + button */}
      <div className="rounded-xl border border-white/10 bg-white/5 backdrop-blur-md p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-gray-200 mb-1">毕业建议</p>
          <p className="text-xs text-gray-400 leading-relaxed">
            当前 Day 3，各项指标均处于达标区间。持续监控 MDD（当前
            -12.3%，基线 -39.7%）和净值趋势，待 Day 55
            后可申请毕业评估。重点关注月度调仓时的滑点偏差变化。
          </p>
        </div>

        <button
          disabled={!canApply}
          onClick={() => navigate("/pipeline")}
          className={[
            "shrink-0 px-5 py-2.5 rounded-lg text-sm font-medium transition-all",
            canApply
              ? "bg-blue-600 hover:bg-blue-500 text-white"
              : "bg-white/5 text-gray-500 border border-white/10 cursor-not-allowed",
          ].join(" ")}
          title={canApply ? "" : "需运行至 Day 55 后方可申请"}
        >
          {canApply ? "申请毕业评估" : `Day ${data.pt_day}/55 解锁`}
        </button>
      </div>
    </div>
  );
}
