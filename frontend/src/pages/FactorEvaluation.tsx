import { useParams } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function FactorEvaluation() {
  const { id, id1, id2 } = useParams<{ id?: string; id1?: string; id2?: string }>();
  const isCompare = Boolean(id1 && id2);

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "因子库", path: "/factors" },
          { label: isCompare ? `对比 ${id1} vs ${id2}` : `因子 ${id ?? "…"} 评估报告` },
        ]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">
            {isCompare ? "因子对比" : "因子评估报告"}
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {isCompare ? `${id1} vs ${id2}` : `Factor ID: ${id ?? "—"}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">编辑重评</Button>
          <Button variant="secondary" size="sm">添加到策略</Button>
          <Button variant="secondary" size="sm">导出PDF</Button>
          <Button variant="danger" size="sm">✗ 丢弃</Button>
          <Button size="sm">✓ 入库</Button>
        </div>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">📊</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">
          {isCompare ? "因子对比视图" : "因子评估报告"}
        </h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：顶部元信息+指标卡（IC/IR/t值/Newey-West t值/FDR校正t值）、6个Tab（IC分析/分组收益/IC衰减/相关性/分年度/分市场状态）。
          {isCompare && " 对比模式为左右双栏视图。"}
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/factor/{"{id}"}/report
        </p>
      </GlassCard>
    </div>
  );
}
