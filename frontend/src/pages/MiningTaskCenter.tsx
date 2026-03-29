import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
  BarChart,
  Bar,
} from "recharts";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { MetricCard } from "@/components/ui/MetricCard";
import { CandidateTable } from "@/components/mining/CandidateTable";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useMiningStore } from "@/store/miningStore";
import {
  getMiningTasks,
  getMiningTaskDetail,
  pauseMiningTask,
  cancelMiningTask,
  retryMiningTask,
  archiveMiningTask,
  getEngineStats,
  submitCandidatesToGate,
} from "@/api/mining";
import type {
  MiningTaskSummary,
  MiningTaskDetail,
  EngineStats,
  MiningEngine,
  CandidateFactor,
} from "@/api/mining";

// ---- Types ----

interface WsProgressMessage {
  type: "progress" | "candidate" | "complete" | "error";
  task_id: string;
  generation?: number;
  total_generations?: number;
  best_fitness?: number;
  avg_fitness?: number;
  discovered?: number;
  passed?: number;
  candidate?: CandidateFactor;
  evolution_point?: { generation: number; best_fitness: number; avg_fitness: number };
}

// ---- Constants ----

const ENGINE_LABEL: Record<MiningEngine, string> = { gp: "GP进化", llm: "LLM生成", bruteforce: "暴力枚举" };
const ENGINE_COLOR: Record<MiningEngine, string> = { gp: "#6c7eff", llm: "#a78bfa", bruteforce: "#34d399" };

type StatusConfig = { label: string; cls: string };
const STATUS_CONFIG: Record<string, StatusConfig> = {
  running: { label: "运行中", cls: "bg-blue-900/60 text-blue-400 border-blue-500/30" },
  paused: { label: "已暂停", cls: "bg-yellow-900/60 text-yellow-400 border-yellow-500/30" },
  completed: { label: "已完成", cls: "bg-green-900/60 text-green-400 border-green-500/30" },
  failed: { label: "失败", cls: "bg-red-900/60 text-red-400 border-red-500/30" },
  cancelled: { label: "已取消", cls: "bg-slate-700 text-slate-400 border-white/10" },
  idle: { label: "空闲", cls: "bg-slate-700 text-slate-400 border-white/10" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG["idle"]!;
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

function formatDuration(startedAt: string, completedAt?: string): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const s = Math.floor((end - start) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

// ---- Task Detail Modal ----

interface TaskDetailModalProps {
  taskId: string;
  onClose: () => void;
  onGateSubmit: (ids: string[]) => Promise<void>;
}

function TaskDetailModal({ taskId, onClose, onGateSubmit }: TaskDetailModalProps) {
  const [detail, setDetail] = useState<MiningTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [gateSubmitting, setGateSubmitting] = useState(false);

  useEffect(() => {
    setLoading(true);
    getMiningTaskDetail(taskId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [taskId]);

  async function handleGate(ids: string[]) {
    setGateSubmitting(true);
    try {
      await onGateSubmit(ids);
      // Refresh detail
      const updated = await getMiningTaskDetail(taskId);
      setDetail(updated);
    } finally {
      setGateSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-4xl mx-4 max-h-[90vh] overflow-y-auto">
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-200">任务详情</h2>
              <p className="text-xs text-slate-500 font-mono mt-0.5">{taskId}</p>
            </div>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-200 text-lg leading-none"
            >
              ✕
            </button>
          </div>

          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-500 text-sm">
              加载中...
            </div>
          )}

          {!loading && !detail && (
            <div className="text-center py-16 text-slate-500 text-sm">任务数据不可用</div>
          )}

          {!loading && detail && (
            <div className="flex flex-col gap-4">
              {/* Summary metrics */}
              <div className="grid grid-cols-4 gap-3">
                <MetricCard label="发现因子" value={detail.discovered} />
                <MetricCard label="Gate通过" value={detail.passed} status="good" />
                <MetricCard label="已入库" value={detail.archived} />
                <MetricCard
                  label="最优IC_IR"
                  value={detail.best_fitness?.toFixed(4) ?? "—"}
                  status={detail.best_fitness && detail.best_fitness > 0.3 ? "good" : "normal"}
                />
              </div>

              {/* Evolution curve */}
              {detail.evolution_history && detail.evolution_history.length > 0 && (
                <div>
                  <h3 className="text-xs font-medium text-slate-400 mb-2">进化曲线回放</h3>
                  <div className="bg-slate-900/50 rounded-xl p-3 border border-white/5">
                    <ResponsiveContainer width="100%" height={180}>
                      <LineChart data={detail.evolution_history} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                        <XAxis dataKey="generation" tick={{ fill: "#7a82a6", fontSize: 10 }} tickLine={false} />
                        <YAxis tick={{ fill: "#7a82a6", fontSize: 10 }} tickLine={false} />
                        <Tooltip
                          contentStyle={{
                            background: "rgba(15,20,45,0.95)",
                            border: "1px solid rgba(100,120,200,0.2)",
                            borderRadius: 8,
                            fontSize: 11,
                          }}
                        />
                        <Legend wrapperStyle={{ fontSize: 11, color: "#7a82a6" }} iconSize={8} iconType="circle" />
                        <Line type="monotone" dataKey="best_fitness" name="最优" stroke="#6c7eff" strokeWidth={1.5} dot={false} />
                        <Line type="monotone" dataKey="avg_fitness" name="平均" stroke="#a78bfa" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {/* Candidates */}
              <div>
                <h3 className="text-xs font-medium text-slate-400 mb-2">产出因子列表</h3>
                <CandidateTable
                  candidates={detail.candidates}
                  onSubmitGate={handleGate}
                  submitting={gateSubmitting}
                />
              </div>
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
}

// ---- Main Page ----

export default function MiningTaskCenter() {
  const { taskId: urlTaskId } = useParams<{ taskId?: string }>();
  const navigate = useNavigate();

  const [tasks, setTasks] = useState<MiningTaskSummary[]>([]);
  const [engineStats, setEngineStats] = useState<EngineStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(urlTaskId ?? null);
  const [actionLoading, setActionLoading] = useState<string | null>(null); // taskId being actioned
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());

  const { upsertTask, updateTask } = useMiningStore();

  // Running task IDs for WebSocket
  const runningIds = tasks.filter((t) => t.status === "running").map((t) => t.task_id);

  // Load tasks + stats
  async function loadData() {
    try {
      const [taskList, stats] = await Promise.all([
        getMiningTasks(),
        getEngineStats().catch(() => [] as EngineStats[]),
      ]);
      setTasks(taskList);
      setEngineStats(stats);
      // Sync to store
      taskList.forEach((t) =>
        upsertTask({
          taskId: t.task_id,
          engine: t.engine,
          status: t.status,
          progress: t.progress,
          generation: t.generation,
          totalGenerations: t.total_generations,
          discovered: t.discovered,
          passed: t.passed,
          startedAt: t.started_at,
          completedAt: t.completed_at,
        })
      );
    } catch (e: unknown) {
      setError((e as Error).message ?? "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    // Poll every 15s for non-WS updates
    const timer = setInterval(loadData, 15000);
    return () => clearInterval(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // WS for first running task (primary)
  const primaryRunningId = runningIds[0] ?? null;
  const { on, off } = useWebSocket({
    namespace: primaryRunningId ? `/ws/factor-mine/${primaryRunningId}` : "",
    enabled: !!primaryRunningId,
  });

  const handleWsMsg = useCallback(
    (msg: WsProgressMessage) => {
      setTasks((prev) =>
        prev.map((t) => {
          if (t.task_id !== msg.task_id) return t;
          return {
            ...t,
            generation: msg.generation ?? t.generation,
            total_generations: msg.total_generations ?? t.total_generations,
            best_fitness: msg.best_fitness ?? t.best_fitness,
            discovered: msg.discovered ?? t.discovered,
            passed: msg.passed ?? t.passed,
            progress:
              msg.generation && msg.total_generations
                ? Math.round((msg.generation / msg.total_generations) * 100)
                : t.progress,
            status: msg.type === "complete" ? "completed" : msg.type === "error" ? "failed" : t.status,
          };
        })
      );
      if (msg.task_id) {
        updateTask(msg.task_id, {
          generation: msg.generation,
          totalGenerations: msg.total_generations,
          status: msg.type === "complete" ? "completed" : msg.type === "error" ? "failed" : undefined,
        });
      }
    },
    [updateTask]
  );

  useEffect(() => {
    if (!primaryRunningId) return;
    on<WsProgressMessage>("message", handleWsMsg);
    return () => off<WsProgressMessage>("message", handleWsMsg);
  }, [primaryRunningId, on, off, handleWsMsg]);

  // Actions
  async function handlePause(taskId: string) {
    setActionLoading(taskId);
    try {
      await pauseMiningTask(taskId);
      setTasks((prev) =>
        prev.map((t) => t.task_id === taskId ? { ...t, status: "paused" } : t)
      );
    } catch {
      setError("暂停失败");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleCancel(taskId: string) {
    setActionLoading(taskId);
    try {
      await cancelMiningTask(taskId);
      setTasks((prev) =>
        prev.map((t) => t.task_id === taskId ? { ...t, status: "cancelled" } : t)
      );
    } catch {
      setError("取消失败");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleRetry(taskId: string) {
    setActionLoading(taskId);
    try {
      // 从任务列表中找到engine类型，用相同engine重启
      const task = tasks.find((t) => t.task_id === taskId);
      const engine = task?.engine ?? "gp";
      const { task_id: newId } = await retryMiningTask(engine);
      await loadData();
      navigate(`/mining/tasks/${newId}`);
    } catch {
      setError("重跑失败");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleArchiveBatch() {
    if (selectedRows.size === 0) return;
    setActionLoading("batch");
    try {
      await Promise.all([...selectedRows].map((id) => archiveMiningTask(id)));
      setSelectedRows(new Set());
      await loadData();
    } catch {
      setError("归档失败");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleGateSubmit(ids: string[]) {
    // Gate评估需要DSL表达式，目前只传占位 — 实际应从task detail获取candidate expressions
    const payloads = ids.map((id) => ({ expr: id, name: undefined }));
    await submitCandidatesToGate(payloads);
  }

  // Running count stats
  const runningCount = tasks.filter((t) => t.status === "running").length;
  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const totalDiscovered = tasks.reduce((s, t) => s + t.discovered, 0);
  const totalPassed = tasks.reduce((s, t) => s + t.passed, 0);

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "因子挖掘", path: "/mining" },
          urlTaskId
            ? { label: "挖掘任务中心", path: "/mining/tasks" }
            : { label: "挖掘任务中心" },
          ...(urlTaskId ? [{ label: `任务 ${urlTaskId.slice(0, 8)}` }] : []),
        ]}
      />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">挖掘任务中心</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {runningCount > 0 ? `${runningCount} 个任务运行中 · ` : ""}
            {tasks.length} 个任务总计
          </p>
        </div>
        <div className="flex gap-2">
          {selectedRows.size > 0 && (
            <Button
              size="sm"
              variant="secondary"
              loading={actionLoading === "batch"}
              onClick={handleArchiveBatch}
            >
              归档所选 ({selectedRows.size})
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={loadData}>
            刷新
          </Button>
          <Button size="sm" onClick={() => navigate("/mining")}>
            + 新建任务
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-center justify-between px-4 py-2.5 rounded-xl bg-red-900/30 border border-red-500/30 text-red-300 text-sm">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-4">✕</button>
        </div>
      )}

      {/* Summary metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <MetricCard label="运行中" value={runningCount} status={runningCount > 0 ? "warning" : "normal"} />
        <MetricCard label="已完成" value={completedCount} status="good" />
        <MetricCard label="总发现因子" value={totalDiscovered} />
        <MetricCard
          label="总通过Gate"
          value={totalPassed}
          subtitle={totalDiscovered > 0 ? `通过率 ${((totalPassed / totalDiscovered) * 100).toFixed(1)}%` : undefined}
          status="good"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_300px] gap-4">
        {/* Task list */}
        <div className="flex flex-col gap-3">
          {loading && (
            <GlassCard>
              <div className="flex items-center justify-center py-16 text-slate-500 text-sm">
                加载中...
              </div>
            </GlassCard>
          )}

          {!loading && tasks.length === 0 && (
            <GlassCard className="flex flex-col items-center justify-center py-16 text-center">
              <div className="text-4xl mb-3">⛏️</div>
              <h2 className="text-base font-semibold text-slate-300 mb-1">暂无挖掘任务</h2>
              <p className="text-sm text-slate-500 mb-4">前往因子实验室启动第一个挖掘任务</p>
              <Button size="sm" onClick={() => navigate("/mining")}>
                前往因子实验室
              </Button>
            </GlassCard>
          )}

          {!loading && tasks.length > 0 && (
            <GlassCard padding="sm">
              <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-white/10 text-slate-400">
                    <th className="pb-2 pr-3 text-left w-8">
                      <input
                        type="checkbox"
                        checked={selectedRows.size === tasks.length && tasks.length > 0}
                        onChange={() =>
                          selectedRows.size === tasks.length
                            ? setSelectedRows(new Set())
                            : setSelectedRows(new Set(tasks.map((t) => t.task_id)))
                        }
                        className="accent-blue-500"
                      />
                    </th>
                    <th className="pb-2 pr-3 text-left">任务ID</th>
                    <th className="pb-2 pr-3 text-left">引擎</th>
                    <th className="pb-2 pr-3 text-center">状态</th>
                    <th className="pb-2 pr-3 text-right">进度</th>
                    <th className="pb-2 pr-3 text-right">发现</th>
                    <th className="pb-2 pr-3 text-right">通过</th>
                    <th className="pb-2 pr-3 text-right">用时</th>
                    <th className="pb-2 text-center">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.map((task) => {
                    const isActioning = actionLoading === task.task_id;
                    return (
                      <tr
                        key={task.task_id}
                        className="border-b border-white/5 hover:bg-white/[0.03] transition-colors"
                      >
                        <td className="py-2.5 pr-3">
                          <input
                            type="checkbox"
                            checked={selectedRows.has(task.task_id)}
                            onChange={() => {
                              const next = new Set(selectedRows);
                              if (next.has(task.task_id)) next.delete(task.task_id);
                              else next.add(task.task_id);
                              setSelectedRows(next);
                            }}
                            className="accent-blue-500"
                          />
                        </td>
                        <td className="py-2.5 pr-3">
                          <button
                            onClick={() => setSelectedTaskId(task.task_id)}
                            className="font-mono text-blue-400 hover:text-blue-300 transition-colors"
                          >
                            {task.task_id?.slice(0, 8) ?? "unknown"}...
                          </button>
                        </td>
                        <td className="py-2.5 pr-3">
                          <span
                            className="px-2 py-0.5 rounded text-[10px] font-medium"
                            style={{
                              background: `${ENGINE_COLOR[task.engine]}20`,
                              color: ENGINE_COLOR[task.engine],
                              border: `1px solid ${ENGINE_COLOR[task.engine]}40`,
                            }}
                          >
                            {ENGINE_LABEL[task.engine]}
                          </span>
                        </td>
                        <td className="py-2.5 pr-3 text-center">
                          <StatusBadge status={task.status} />
                        </td>
                        <td className="py-2.5 pr-3">
                          <div className="flex items-center gap-1.5 justify-end">
                            <div className="w-16 bg-slate-800 rounded-full h-1">
                              <div
                                className="bg-blue-500 h-1 rounded-full transition-all"
                                style={{ width: `${task.progress}%` }}
                              />
                            </div>
                            <span className="text-slate-400 w-7 text-right">{task.progress}%</span>
                          </div>
                          {task.generation !== undefined && task.total_generations && (
                            <div className="text-[10px] text-slate-500 text-right mt-0.5">
                              {task.generation}/{task.total_generations}代
                            </div>
                          )}
                        </td>
                        <td className="py-2.5 pr-3 text-right text-slate-300 font-mono">
                          {task.discovered}
                        </td>
                        <td className="py-2.5 pr-3 text-right text-green-400 font-mono">
                          {task.passed}
                        </td>
                        <td className="py-2.5 pr-3 text-right text-slate-400">
                          {formatDuration(task.started_at, task.completed_at)}
                        </td>
                        <td className="py-2.5 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => setSelectedTaskId(task.task_id)}
                              className="px-1.5 py-0.5 text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                              title="详情"
                            >
                              详情
                            </button>
                            {task.status === "running" && (
                              <button
                                onClick={() => handlePause(task.task_id)}
                                disabled={isActioning}
                                className="px-1.5 py-0.5 text-[10px] text-yellow-400 hover:text-yellow-300 transition-colors disabled:opacity-40"
                                title="暂停"
                              >
                                暂停
                              </button>
                            )}
                            {(task.status === "running" || task.status === "paused") && (
                              <button
                                onClick={() => handleCancel(task.task_id)}
                                disabled={isActioning}
                                className="px-1.5 py-0.5 text-[10px] text-red-400 hover:text-red-300 transition-colors disabled:opacity-40"
                                title="取消"
                              >
                                取消
                              </button>
                            )}
                            {(task.status === "failed" || task.status === "completed") && (
                              <button
                                onClick={() => handleRetry(task.task_id)}
                                disabled={isActioning}
                                className="px-1.5 py-0.5 text-[10px] text-slate-400 hover:text-slate-300 transition-colors disabled:opacity-40"
                                title="重跑"
                              >
                                重跑
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              </div>
            </GlassCard>
          )}
        </div>

        {/* Right: engine stats */}
        <div className="flex flex-col gap-3">
          <GlassCard>
            <h3 className="text-sm font-semibold text-slate-200 mb-3">引擎效率对比</h3>
            {engineStats.length === 0 ? (
              <div className="text-xs text-slate-500 py-4 text-center">暂无统计数据</div>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={140}>
                  <BarChart
                    data={engineStats.map((s) => ({
                      name: ENGINE_LABEL[s.engine],
                      通过率: +(s.pass_rate * 100).toFixed(1),
                      入库率: +(s.archive_rate * 100).toFixed(1),
                    }))}
                    margin={{ top: 4, right: 4, left: -24, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="name" tick={{ fill: "#7a82a6", fontSize: 10 }} tickLine={false} />
                    <YAxis
                      tick={{ fill: "#7a82a6", fontSize: 10 }}
                      tickLine={false}
                      unit="%"
                    />
                    <Tooltip
                      contentStyle={{
                        background: "rgba(15,20,45,0.95)",
                        border: "1px solid rgba(100,120,200,0.2)",
                        borderRadius: 8,
                        fontSize: 11,
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, color: "#7a82a6" }} iconSize={8} iconType="circle" />
                    <Bar dataKey="通过率" fill="#6c7eff" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="入库率" fill="#34d399" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>

                <div className="mt-3 flex flex-col gap-2">
                  {engineStats.map((s) => (
                    <div
                      key={s.engine}
                      className="flex items-center justify-between text-xs px-2 py-1.5 rounded-lg bg-slate-800/50"
                    >
                      <span
                        className="font-medium"
                        style={{ color: ENGINE_COLOR[s.engine] }}
                      >
                        {ENGINE_LABEL[s.engine]}
                      </span>
                      <div className="flex gap-3 text-slate-400">
                        <span>{s.total_tasks} 次</span>
                        <span className="text-slate-300">{(s.pass_rate * 100).toFixed(0)}% 通过</span>
                        <span className="text-green-400">{(s.archive_rate * 100).toFixed(0)}% 入库</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </GlassCard>

          {/* Running task live monitor */}
          {runningIds.length > 0 && (
            <GlassCard variant="glow">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                <h3 className="text-sm font-semibold text-slate-200">实时监控</h3>
              </div>
              {tasks
                .filter((t) => t.status === "running")
                .map((t) => (
                  <div key={t.task_id} className="mb-3 last:mb-0">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-mono text-slate-400">{t.task_id?.slice(0, 12) ?? "unknown"}...</span>
                      <span
                        className="text-[10px] font-medium"
                        style={{ color: ENGINE_COLOR[t.engine] }}
                      >
                        {ENGINE_LABEL[t.engine]}
                      </span>
                    </div>
                    {t.generation !== undefined && t.total_generations && (
                      <div className="text-xs text-slate-400 mb-1">
                        第 <span className="text-slate-200 font-mono">{t.generation}</span> /
                        {t.total_generations} 代
                        {t.best_fitness !== undefined && (
                          <span className="ml-2 text-green-400 font-mono">
                            最优 {t.best_fitness.toFixed(4)}
                          </span>
                        )}
                      </div>
                    )}
                    <div className="w-full bg-slate-800 rounded-full h-1.5">
                      <div
                        className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
                        style={{ width: `${t.progress}%` }}
                      />
                    </div>
                    <div className="flex justify-between mt-1 text-[10px] text-slate-500">
                      <span>发现 {t.discovered} | 通过 {t.passed}</span>
                      <span>{formatDuration(t.started_at)}</span>
                    </div>
                  </div>
                ))}
            </GlassCard>
          )}
        </div>
      </div>

      {/* Task detail modal */}
      {selectedTaskId && (
        <TaskDetailModal
          taskId={selectedTaskId}
          onClose={() => setSelectedTaskId(null)}
          onGateSubmit={handleGateSubmit}
        />
      )}
    </div>
  );
}
