import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function BacktestConfig() {
  return (
    <div>
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: "回测配置" },
        ]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">回测配置</h1>
          <p className="text-sm text-slate-400 mt-0.5">6个配置Tab</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">取消</Button>
          <Button size="sm">▶ 运行回测</Button>
        </div>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">🔬</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">回测配置面板</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示6个Tab：市场/股票池、时间段、执行参数、成本模型、风控/高级、动态仓位。底部资金量约束黄色警告条。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: POST /api/backtest/run
        </p>
      </GlassCard>
    </div>
  );
}
