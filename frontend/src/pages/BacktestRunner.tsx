import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { useBacktestProgress } from "@/hooks/useBacktestProgress";
import { cancelBacktest, type BacktestProgress } from "@/api/backtest";

function statusLabel(status: BacktestProgress["status"]): string {
  const map: Record<BacktestProgress["status"], string> = {
    waiting: "等待中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return map[status] ?? status;
}

function statusColor(status: BacktestProgress["status"]): string {
  const map: Record<BacktestProgress["status"], string> = {
    waiting: "text-slate-400",
    running: "text-blue-400",
    completed: "text-green-400",
    failed: "text-red-400",
    cancelled: "text-slate-500",
  };
  return map[status] ?? "text-slate-400";
}

function formatSeconds(secs: number | null): string {
  if (secs === null || secs < 0) return "—";
  if (secs < 60) return `${Math.round(secs)}s`;
  return `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`;
}

function NavChart({ data }: { data: Array<{ date: string; nav: number }> }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        等待数据...
      </div>
    );
  }

  const option = {
    backgroundColor: "transparent",
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: "category",
      data: data.map((d) => d.date),
      axisLine: { lineStyle: { color: "#334155" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "#334155" } },
      splitLine: { lineStyle: { color: "#1e293b" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
    },
    series: [
      {
        type: "line",
        data: data.map((d) => d.nav),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#60a5fa", width: 2 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(96,165,250,0.2)" },
              { offset: 1, color: "rgba(96,165,250,0.02)" },
            ],
          },
        },
      },
    ],
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(15,20,45,0.9)",
      borderColor: "#334155",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
    },
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: "100%", width: "100%" }}
      notMerge={false}
      lazyUpdate
    />
  );
}

function LogEntry({ level, ts, msg }: { level: string; ts: string; msg: string }) {
  const colorMap: Record<string, string> = {
    info: "text-slate-300",
    warn: "text-yellow-400",
    error: "text-red-400",
  };
  return (
    <div className={`flex gap-2 text-xs font-mono ${colorMap[level] ?? "text-slate-300"}`}>
      <span className="text-slate-500 shrink-0">{ts}</span>
      <span className={`shrink-0 uppercase text-[10px] ${colorMap[level]}`}>[{level}]</span>
      <span className="break-all">{msg}</span>
    </div>
  );
}

export default function BacktestRunner() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const logContainerRef = useRef<HTMLDivElement>(null);
  const [cancelling, setCancelling] = useState(false);

  const { progress, isConnected, isPolling, error } = useBacktestProgress({
    runId,
    enabled: !!runId,
  });

  // Auto-scroll logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [progress?.logs]);

  // Redirect to results on completion
  useEffect(() => {
    if (progress?.status === "completed" && runId) {
      const timer = setTimeout(() => {
        navigate(`/backtest/${runId}/result`);
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [progress?.status, runId, navigate]);

  const handleCancel = async () => {
    if (!runId || cancelling) return;
    setCancelling(true);
    try {
      await cancelBacktest(runId);
    } catch {
      // ignore — progress WS will reflect cancelled state
    } finally {
      setCancelling(false);
    }
  };

  const isTerminal =
    progress?.status === "completed" ||
    progress?.status === "failed" ||
    progress?.status === "cancelled";

  const pct = progress?.progress ?? 0;

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: `运行 #${runId ?? "…"}` },
        ]}
      />

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">回测运行监控</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Run ID: {runId ?? "—"}
            {isConnected && (
              <span className="ml-2 inline-flex items-center gap-1 text-green-400">
                <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                WebSocket
              </span>
            )}
            {isPolling && !isConnected && (
              <span className="ml-2 text-yellow-400">轮询中</span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate("/backtest/config")}
          >
            后台运行
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={isTerminal || cancelling}
            loading={cancelling}
            onClick={handleCancel}
          >
            取消回测
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 px-4 py-2 rounded-xl bg-red-900/30 border border-red-500/40 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Progress bar + status */}
      <GlassCard className="mb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className={`font-semibold ${statusColor(progress?.status ?? "waiting")}`}>
              {statusLabel(progress?.status ?? "waiting")}
            </span>
            {progress?.current_window && (
              <span className="text-xs text-slate-400 bg-slate-700/50 px-2 py-0.5 rounded">
                WF窗口 {progress.current_window}
              </span>
            )}
            {progress?.current_date && (
              <span className="text-xs text-slate-500">{progress.current_date}</span>
            )}
          </div>
          <div className="text-right text-sm">
            <span className="text-white font-medium">{pct.toFixed(1)}%</span>
            {progress?.estimated_remaining_seconds !== undefined && (
              <span className="text-slate-400 ml-2">
                剩余 {formatSeconds(progress.estimated_remaining_seconds)}
              </span>
            )}
            {progress?.elapsed_seconds !== undefined && (
              <span className="text-slate-500 ml-2">
                已用 {formatSeconds(progress.elapsed_seconds)}
              </span>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div className="w-full h-2 bg-slate-700/60 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              progress?.status === "failed"
                ? "bg-red-500"
                : progress?.status === "completed"
                ? "bg-green-500"
                : "bg-blue-500"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>

        {progress?.status === "completed" && (
          <p className="mt-2 text-xs text-green-400 text-center">
            回测完成，正在跳转到结果页...
          </p>
        )}
      </GlassCard>

      {/* Realtime metrics + NAV chart */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        {/* Realtime metrics */}
        <div className="lg:col-span-1 grid grid-cols-2 gap-3 content-start">
          <GlassCard padding="sm">
            <p className="text-xs text-slate-400 mb-1">实时 Sharpe</p>
            <p className="text-xl font-bold text-white">
              {progress?.sharpe_realtime?.toFixed(3) ?? "—"}
            </p>
          </GlassCard>
          <GlassCard padding="sm">
            <p className="text-xs text-slate-400 mb-1">实时 MDD</p>
            <p className="text-xl font-bold text-red-400">
              {progress?.mdd_realtime != null
                ? `${(progress.mdd_realtime * 100).toFixed(1)}%`
                : "—"}
            </p>
          </GlassCard>
          <GlassCard padding="sm" className="col-span-2">
            <p className="text-xs text-slate-400 mb-1">进度 {pct.toFixed(0)}%</p>
            <div className="w-full bg-slate-700/60 rounded-full h-1.5">
              <div
                className="h-1.5 bg-blue-500 rounded-full transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </GlassCard>
        </div>

        {/* NAV chart */}
        <GlassCard className="lg:col-span-2 h-48">
          <p className="text-xs text-slate-400 mb-2">实时净值曲线</p>
          <div className="h-36">
            <NavChart data={progress?.nav_realtime ?? []} />
          </div>
        </GlassCard>
      </div>

      {/* Log stream */}
      <GlassCard>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-medium text-slate-200">运行日志</p>
          <span className="text-xs text-slate-500">
            {progress?.logs?.length ?? 0} 条
          </span>
        </div>
        <div
          ref={logContainerRef}
          className="h-56 overflow-y-auto space-y-1 pr-1"
          style={{ scrollbarWidth: "thin", scrollbarColor: "#334155 transparent" }}
        >
          {(!progress?.logs || progress.logs.length === 0) ? (
            <p className="text-xs text-slate-500 text-center py-8">等待日志...</p>
          ) : (
            progress.logs.map((log, i) => (
              <LogEntry key={i} level={log.level} ts={log.ts} msg={log.msg} />
            ))
          )}
        </div>
      </GlassCard>
    </div>
  );
}
