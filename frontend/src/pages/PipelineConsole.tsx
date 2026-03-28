import { useState, useEffect, useCallback, useRef } from "react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { FlowChart } from "@/components/pipeline/FlowChart";
import { ApprovalPanel } from "@/components/pipeline/ApprovalPanel";
import { PipelineHistory } from "@/components/pipeline/PipelineHistory";
import {
  getPipelineStatus,
  getPendingApprovals,
  getPipelineHistory,
  getPipelineLogs,
  triggerPipeline,
  pausePipeline,
  approveItem,
  rejectItem,
  holdItem,
  setAutomationLevel,
  type PipelineStatus,
  type ApprovalItem,
  type PipelineRun,
  type PipelineLogEntry,
  type AutomationLevel,
} from "@/api/pipeline";
import { useNavigate } from "react-router-dom";

const AUTOMATION_LEVELS: { id: AutomationLevel; label: string; desc: string }[] = [
  { id: "L0", label: "L0", desc: "纯手动" },
  { id: "L1", label: "L1", desc: "半自动" },
  { id: "L2", label: "L2", desc: "自动+审批" },
  { id: "L3", label: "L3", desc: "全自动" },
];

const LOG_LEVEL_COLORS: Record<string, string> = {
  info:     "text-slate-400",
  warning:  "text-yellow-400",
  error:    "text-red-400",
  decision: "text-blue-300",
};

const TABS = ["状态流程", "待审批", "运行历史", "AI决策日志"] as const;
type Tab = (typeof TABS)[number];

// Mock empty state for use when API not yet available
const EMPTY_STATUS: PipelineStatus = {
  run_id: null,
  automation_level: "L1",
  is_running: false,
  is_paused: false,
  current_node: null,
  nodes: [],
  schedule_cron: "0 20 * * 1-5",
  next_run_at: null,
  last_run_at: null,
};

export default function PipelineConsole() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>("状态流程");
  const [status, setStatus] = useState<PipelineStatus>(EMPTY_STATUS);
  const [pending, setPending] = useState<ApprovalItem[]>([]);
  const [history, setHistory] = useState<PipelineRun[]>([]);
  const [logs, setLogs] = useState<PipelineLogEntry[]>([]);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingPending, setLoadingPending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load pipeline status
  const loadStatus = useCallback(async () => {
    try {
      const data = await getPipelineStatus();
      setStatus(data);
      setError(null);
    } catch {
      setError("无法加载 Pipeline 状态，请检查后端连接");
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  const loadPending = useCallback(async () => {
    setLoadingPending(true);
    try {
      const data = await getPendingApprovals();
      setPending(data);
    } catch {
      // silent
    } finally {
      setLoadingPending(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const data = await getPipelineHistory();
      setHistory(data);
    } catch {
      // silent
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  const loadLogs = useCallback(async () => {
    if (!status.run_id) return;
    setLoadingLogs(true);
    try {
      const data = await getPipelineLogs(status.run_id);
      setLogs(data);
    } catch {
      // silent
    } finally {
      setLoadingLogs(false);
    }
  }, [status.run_id]);

  // Initial load + polling
  useEffect(() => {
    loadStatus();
    pollingRef.current = setInterval(loadStatus, 10_000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [loadStatus]);

  // Load tab-specific data when switching tabs
  useEffect(() => {
    if (activeTab === "待审批") loadPending();
    else if (activeTab === "运行历史") loadHistory();
    else if (activeTab === "AI决策日志") loadLogs();
  }, [activeTab, loadPending, loadHistory, loadLogs]);

  // WebSocket connection when pipeline is running
  useEffect(() => {
    if (!status.run_id || !status.is_running) {
      wsRef.current?.close();
      wsRef.current = null;
      return;
    }
    const wsBase = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? "ws://localhost:8000";
    const ws = new WebSocket(`${wsBase}/ws/pipeline/${status.run_id}`);
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data as string) as { type: string; payload: unknown };
        if (msg.type === "status_update") {
          setStatus((prev) => ({ ...prev, ...(msg.payload as Partial<PipelineStatus>) }));
        } else if (msg.type === "log") {
          setLogs((prev) => [msg.payload as PipelineLogEntry, ...prev].slice(0, 200));
        }
      } catch {
        // ignore malformed messages
      }
    };
    wsRef.current = ws;
    return () => ws.close();
  }, [status.run_id, status.is_running]);

  // Handlers
  const handleTrigger = async () => {
    setTriggering(true);
    try {
      await triggerPipeline();
      await loadStatus();
    } catch {
      setError("触发失败，请重试");
    } finally {
      setTriggering(false);
    }
  };

  const handlePause = async () => {
    try {
      await pausePipeline();
      await loadStatus();
    } catch {
      setError("暂停操作失败");
    }
  };

  const handleLevelChange = async (level: AutomationLevel) => {
    try {
      await setAutomationLevel(level);
      setStatus((prev) => ({ ...prev, automation_level: level }));
    } catch {
      setError("自动化级别设置失败");
    }
  };

  const handleApprove = async (id: string, note?: string) => {
    await approveItem(id, note);
    setPending((prev) => prev.map((p) => p.id === id ? { ...p, decision: "approved" as const } : p));
  };

  const handleReject = async (id: string, note?: string) => {
    await rejectItem(id, note);
    setPending((prev) => prev.map((p) => p.id === id ? { ...p, decision: "rejected" as const } : p));
  };

  const handleHold = async (id: string, note?: string) => {
    await holdItem(id, note);
    setPending((prev) => prev.map((p) => p.id === id ? { ...p, decision: "hold" as const } : p));
  };

  const pendingCount = pending.filter((p) => !p.decision).length;

  return (
    <div>
      <Breadcrumb items={[{ label: "AI闭环" }, { label: "Pipeline控制台" }]} />

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">AI Pipeline 控制台</h1>
          <p className="text-sm text-slate-400 mt-0.5">自动化级别 · 待审批队列 · 运行历史</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={handlePause}
            disabled={!status.is_running}
          >
            {status.is_paused ? "继续" : "暂停"}
          </Button>
          <Button
            size="sm"
            loading={triggering}
            onClick={handleTrigger}
            disabled={status.is_running}
          >
            手动触发 Pipeline
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/pipeline/agents")}
          >
            Agent配置 →
          </Button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 flex items-center justify-between bg-red-900/30 border border-red-500/30 rounded-xl px-4 py-2.5">
          <span className="text-sm text-red-300">{error}</span>
          <button className="text-xs text-red-400 hover:text-red-200" onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* Automation level selector */}
      <GlassCard className="mb-4">
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-400 shrink-0">自动化级别</span>
          <div className="flex gap-2">
            {AUTOMATION_LEVELS.map(({ id, label, desc }) => {
              const active = status.automation_level === id;
              return (
                <button
                  key={id}
                  onClick={() => handleLevelChange(id)}
                  title={desc}
                  className={[
                    "px-4 py-1.5 text-xs font-semibold rounded-lg border transition-all duration-150",
                    active
                      ? "bg-blue-600/20 border-blue-500/40 text-blue-300 shadow-[0_0_8px_rgba(96,165,250,0.2)]"
                      : "bg-transparent border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20",
                  ].join(" ")}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <span className="text-xs text-slate-500">
            当前: {AUTOMATION_LEVELS.find((l) => l.id === status.automation_level)?.desc}
          </span>
          {status.next_run_at && (
            <span className="ml-auto text-xs text-slate-500">
              下次执行: {new Date(status.next_run_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      </GlassCard>

      {/* Status indicator */}
      <div className="flex items-center gap-3 mb-4">
        <div className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1 rounded-full border ${
          status.is_running
            ? "text-blue-300 bg-blue-500/15 border-blue-500/30"
            : "text-slate-400 bg-slate-800/40 border-white/10"
        }`}>
          <span className={`w-2 h-2 rounded-full ${status.is_running ? "bg-blue-400 animate-pulse" : "bg-slate-600"}`} />
          {status.is_running ? (status.is_paused ? "已暂停" : "运行中") : "空闲"}
        </div>
        {status.last_run_at && (
          <span className="text-xs text-slate-500">
            上次运行: {new Date(status.last_run_at).toLocaleString("zh-CN")}
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-white/5 pb-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={[
              "relative px-4 py-2 text-xs font-medium rounded-t-lg transition-colors duration-150",
              activeTab === tab
                ? "text-blue-300 bg-blue-500/10"
                : "text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {tab}
            {tab === "待审批" && pendingCount > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 text-[10px] font-bold bg-red-500/80 text-white rounded-full">
                {pendingCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "状态流程" && (
        <div className="space-y-4">
          <GlassCard>
            <p className="text-xs font-semibold text-slate-400 mb-4">
              Pipeline 状态图
              {status.current_node && (
                <span className="ml-2 text-blue-300">当前节点: {status.current_node}</span>
              )}
            </p>
            {loadingStatus ? (
              <div className="h-24 rounded-xl bg-slate-800/40 animate-pulse" />
            ) : (
              <FlowChart nodes={status.nodes} currentNode={status.current_node} />
            )}
          </GlassCard>

          {/* Schedule info */}
          <GlassCard>
            <p className="text-xs font-semibold text-slate-400 mb-3">调度配置</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
              <div>
                <p className="text-slate-500 mb-1">Cron 表达式</p>
                <p className="text-slate-200 font-mono">{status.schedule_cron}</p>
              </div>
              <div>
                <p className="text-slate-500 mb-1">下次执行</p>
                <p className="text-slate-200">
                  {status.next_run_at
                    ? new Date(status.next_run_at).toLocaleString("zh-CN")
                    : "未配置"}
                </p>
              </div>
              <div>
                <p className="text-slate-500 mb-1">上次执行</p>
                <p className="text-slate-200">
                  {status.last_run_at
                    ? new Date(status.last_run_at).toLocaleString("zh-CN")
                    : "从未运行"}
                </p>
              </div>
              <div>
                <p className="text-slate-500 mb-1">当前运行 ID</p>
                <p className="text-slate-400 font-mono text-[11px]">
                  {status.run_id ? `${status.run_id.slice(0, 8)}...` : "—"}
                </p>
              </div>
            </div>
          </GlassCard>
        </div>
      )}

      {activeTab === "待审批" && (
        <ApprovalPanel
          items={pending}
          loading={loadingPending}
          onApprove={handleApprove}
          onReject={handleReject}
          onHold={handleHold}
        />
      )}

      {activeTab === "运行历史" && (
        <PipelineHistory runs={history} loading={loadingHistory} />
      )}

      {activeTab === "AI决策日志" && (
        <GlassCard padding="sm">
          <div className="flex items-center justify-between mb-3 px-1">
            <p className="text-xs font-semibold text-slate-400">AI 决策日志</p>
            <Button size="sm" variant="ghost" onClick={loadLogs} disabled={loadingLogs}>
              {loadingLogs ? "加载中..." : "刷新"}
            </Button>
          </div>
          {loadingLogs ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-8 rounded-lg bg-slate-800/40 animate-pulse" />
              ))}
            </div>
          ) : logs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <span className="text-3xl mb-2">📝</span>
              <p className="text-sm text-slate-400">暂无日志</p>
              <p className="text-xs text-slate-500 mt-1">
                {status.run_id ? "日志加载中..." : "触发 Pipeline 后查看日志"}
              </p>
            </div>
          ) : (
            <div className="space-y-1 max-h-[500px] overflow-y-auto">
              {logs.map((log) => (
                <div key={log.id} className="flex gap-3 text-xs py-1.5 px-2 rounded hover:bg-white/[0.03]">
                  <span className="text-slate-600 shrink-0 font-mono text-[10px] pt-0.5">
                    {new Date(log.timestamp).toLocaleTimeString("zh-CN")}
                  </span>
                  <span className="text-slate-500 shrink-0 w-16 truncate">[{log.agent}]</span>
                  <span className={LOG_LEVEL_COLORS[log.level] ?? "text-slate-400"}>{log.content}</span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
}
