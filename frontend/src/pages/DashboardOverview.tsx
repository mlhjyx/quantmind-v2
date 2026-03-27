import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function DashboardOverview() {
  return (
    <div>
      <Breadcrumb />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">总览</h1>
          <p className="text-sm text-slate-400 mt-0.5">总组合 · v1.1配置</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">▶ 运行回测</Button>
          <Button variant="secondary" size="sm">🔍 因子体检</Button>
          <Button variant="secondary" size="sm">📊 周报</Button>
        </div>
      </div>

      {/* Empty state */}
      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">📊</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">
          总览数据加载中
        </h2>
        <p className="text-sm text-slate-400 max-w-sm">
          连接后端后将显示：组合净值、今日收益、Sharpe、MDD、仓位、待处理事项、分市场卡片、净值曲线及月度收益。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/dashboard/summary · GET /api/dashboard/nav-series
        </p>
      </GlassCard>
    </div>
  );
}
