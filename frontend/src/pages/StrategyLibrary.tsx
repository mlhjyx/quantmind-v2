import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function StrategyLibrary() {
  return (
    <div>
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: "策略库" },
        ]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">策略库</h1>
          <p className="text-sm text-slate-400 mt-0.5">历史回测 · 收藏 · 对比</p>
        </div>
        <Button size="sm">+ 新建策略</Button>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">📚</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">策略库</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：策略列表（卡片/表格切换）、筛选/排序/搜索、对比模式（勾选2个→双栏对比：指标+净值+因子重叠+月度胜负）、回测历史时间倒序。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/strategy · GET /api/backtest/history
        </p>
      </GlassCard>
    </div>
  );
}
