import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";

export default function DashboardAstock() {
  return (
    <div>
      <Breadcrumb
        items={[
          { label: "总览", path: "/dashboard" },
          { label: "A股详情" },
        ]}
      />
      <div className="flex items-center gap-3 mb-6">
        <Link
          to="/dashboard"
          className="text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          ← 返回总览
        </Link>
        <h1 className="text-2xl font-bold text-white">A股详情</h1>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">🇨🇳</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">
          A股详情视图
        </h2>
        <p className="text-sm text-slate-400 max-w-sm">
          将显示：完整7指标卡、净值曲线（仓位水位+事件标注）、行业分布、因子库状态、AI闭环状态、月度热力图、快速操作栏。
        </p>
        <p className="text-xs text-slate-500 mt-4">路由: /dashboard/astock</p>
      </GlassCard>
    </div>
  );
}
