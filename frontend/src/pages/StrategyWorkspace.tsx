import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function StrategyWorkspace() {
  return (
    <div>
      <Breadcrumb
        items={[{ label: "策略工作台" }]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">策略工作台</h1>
          <p className="text-sm text-slate-400 mt-0.5">可视化模式 · 代码模式</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">保存</Button>
          <Button size="sm">▶ 运行回测</Button>
        </div>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">⚡</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">策略工作台</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：左栏因子面板（34因子按类别折叠）、中央策略编辑区（可视化流程图/Monaco代码编辑器双模式）、右栏AI助手（260px）、底部资金量约束提示。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/strategy · POST /api/strategy · POST /api/ai/strategy-assist
        </p>
      </GlassCard>
    </div>
  );
}
