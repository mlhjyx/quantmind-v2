import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function FactorLibrary() {
  return (
    <div>
      <Breadcrumb items={[{ label: "因子库" }]} />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">因子库</h1>
          <p className="text-sm text-slate-400 mt-0.5">活跃 · 新入库 · 衰退 · 淘汰</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">因子体检</Button>
          <Button variant="secondary" size="sm">相关性裁剪</Button>
          <Button variant="secondary" size="sm">导出</Button>
          <Button size="sm">+ 添加</Button>
        </div>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">🧬</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">因子库</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：顶部统计（活跃N/新入库N/衰退N/淘汰N）、因子表格（状态/名称/类别/IC/IR/来源/FDR t值）、健康度面板（相关性热力图+分类饼图+IC趋势监控）。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/factor/library · POST /api/factor/health-check
        </p>
      </GlassCard>
    </div>
  );
}
