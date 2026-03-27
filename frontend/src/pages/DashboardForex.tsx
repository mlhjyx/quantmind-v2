import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";

export default function DashboardForex() {
  return (
    <div>
      <Breadcrumb
        items={[
          { label: "总览", path: "/dashboard" },
          { label: "外汇详情" },
        ]}
      />
      <div className="flex items-center gap-3 mb-6">
        <Link
          to="/dashboard"
          className="text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          ← 返回总览
        </Link>
        <h1 className="text-2xl font-bold text-white">外汇详情</h1>
        <span className="text-xs bg-slate-700 text-slate-400 px-2 py-0.5 rounded-full">
          Phase 2
        </span>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">💱</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">
          外汇模块 — Phase 2 即将开放
        </h2>
        <p className="text-sm text-slate-400 max-w-sm">
          将显示：账户净值、保证金使用率、活跃持仓、净值曲线（含夜盘）、货币敞口、风控状态、Swap预估、经济日历。
        </p>
        <p className="text-xs text-slate-500 mt-4">路由: /dashboard/forex</p>
      </GlassCard>
    </div>
  );
}
