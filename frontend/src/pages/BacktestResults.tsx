import { useParams } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function BacktestResults() {
  const { runId } = useParams<{ runId: string }>();

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: `运行 #${runId ?? "…"}`, path: `/backtest/${runId}` },
          { label: "结果分析" },
        ]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">回测结果分析</h1>
          <p className="text-sm text-slate-400 mt-0.5">Run ID: {runId ?? "—"}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">修改重跑</Button>
          <Button variant="secondary" size="sm">复制策略</Button>
          <Button variant="secondary" size="sm">导出PDF</Button>
          <Button size="sm">部署到模拟盘</Button>
        </div>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">📈</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">回测结果分析</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：顶部8指标卡（年化/Sharpe/DSR/MDD/Calmar/换手/扣费收益/WF-OOS Sharpe）+ 8个Tab（净值曲线/月度归因/持仓分析/交易明细/WF分析/参数敏感性/实盘对比/仓位分析）。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/backtest/{"{runId}"}/result
        </p>
      </GlassCard>
    </div>
  );
}
