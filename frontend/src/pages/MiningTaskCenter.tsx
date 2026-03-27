import { useParams } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";

export default function MiningTaskCenter() {
  const { taskId } = useParams<{ taskId?: string }>();

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "因子挖掘", path: "/mining" },
          taskId
            ? { label: `任务 ${taskId}` }
            : { label: "挖掘任务中心" },
        ]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">挖掘任务中心</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {taskId ? `任务 ID: ${taskId}` : "运行中 · 已完成 · 统计"}
          </p>
        </div>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">🎯</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">挖掘任务中心</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：运行中任务（进度条+实时指标+GP进化曲线）、已完成任务（✅/❌标记+生成/通过/入库统计）、GP/LLM/枚举命中率统计。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          WebSocket: /ws/factor-mine/{"{taskId}"}
        </p>
      </GlassCard>
    </div>
  );
}
