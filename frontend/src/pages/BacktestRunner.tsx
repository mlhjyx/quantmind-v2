import { useParams } from "react-router-dom";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

export default function BacktestRunner() {
  const { runId } = useParams<{ runId: string }>();

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: `运行 #${runId ?? "…"}` },
        ]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">回测运行监控</h1>
          <p className="text-sm text-slate-400 mt-0.5">Run ID: {runId ?? "—"}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">后台运行</Button>
          <Button variant="danger" size="sm">取消回测</Button>
        </div>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">⏳</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">回测运行监控</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：进度条+百分比+预估剩余时间、WF窗口进度、实时指标+净值曲线（ECharts动态追加）、运行日志。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          WebSocket: /ws/backtest/{"{runId}"}
        </p>
      </GlassCard>
    </div>
  );
}
