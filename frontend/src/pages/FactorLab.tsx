import { useState, useCallback, useEffect } from "react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { GPPanel } from "@/components/mining/GPPanel";
import { LLMPanel } from "@/components/mining/LLMPanel";
import { BruteForcePanel } from "@/components/mining/BruteForcePanel";
import { CandidateTable } from "@/components/mining/CandidateTable";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useMiningStore } from "@/store/miningStore";
import {
  startGPMining,
  startLLMMining,
  startBruteForceMining,
  submitCandidatesToGate,
  getMiningTaskDetail,
} from "@/api/mining";
import type { GPConfig, LLMConfig, BruteForceConfig, CandidateFactor, MiningEngine } from "@/api/mining";

type ModeTab = "gp" | "llm" | "bruteforce";

const MODE_TABS: { key: ModeTab; label: string; desc: string }[] = [
  { key: "gp", label: "GP遗传编程", desc: "自动进化因子表达式" },
  { key: "llm", label: "LLM生成", desc: "AI根据投资假设生成" },
  { key: "bruteforce", label: "暴力枚举", desc: "系统性参数网格搜索" },
];

interface WsProgressMessage {
  type: "progress" | "candidate" | "complete" | "error";
  task_id: string;
  generation?: number;
  total_generations?: number;
  best_fitness?: number;
  avg_fitness?: number;
  candidate?: CandidateFactor;
  evolution_point?: { generation: number; best_fitness: number; avg_fitness: number };
}

export default function FactorLab() {
  const [activeMode, setActiveMode] = useState<ModeTab>("gp");
  const [submitting, setSubmitting] = useState(false);
  const [gateSubmitting, setGateSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // local candidates list (merged from WS + initial load)
  const [candidates, setCandidates] = useState<CandidateFactor[]>([]);
  const [evolutionHistory, setEvolutionHistory] = useState<
    { generation: number; best_fitness: number; avg_fitness: number }[]
  >([]);
  const [currentGeneration, setCurrentGeneration] = useState<number | undefined>();
  const [totalGenerations, setTotalGenerations] = useState<number | undefined>();
  const [bestFitness, setBestFitness] = useState<number | undefined>();

  const { activeTaskId, tasks, setActiveTask, upsertTask, updateTask } = useMiningStore();

  const activeTask = activeTaskId ? tasks[activeTaskId] : null;
  const isRunning = activeTask?.status === "running";
  const isPaused = activeTask?.status === "paused";

  // WebSocket for active task
  const wsEnabled = !!activeTaskId && (isRunning || isPaused);
  const { on, off } = useWebSocket({
    namespace: activeTaskId ? `/ws/factor-mine/${activeTaskId}` : "",
    enabled: wsEnabled,
  });

  const handleWsMessage = useCallback(
    (msg: WsProgressMessage) => {
      if (!activeTaskId || msg.task_id !== activeTaskId) return;

      if (msg.type === "progress") {
        if (msg.generation !== undefined) setCurrentGeneration(msg.generation);
        if (msg.total_generations !== undefined) setTotalGenerations(msg.total_generations);
        if (msg.best_fitness !== undefined) setBestFitness(msg.best_fitness);
        if (msg.evolution_point) {
          setEvolutionHistory((prev) => [...prev, msg.evolution_point!]);
        }
        updateTask(activeTaskId, {
          generation: msg.generation,
          totalGenerations: msg.total_generations,
          progress: msg.generation && msg.total_generations
            ? Math.round((msg.generation / msg.total_generations) * 100)
            : 0,
        });
      } else if (msg.type === "candidate" && msg.candidate) {
        setCandidates((prev) => {
          const exists = prev.some((c) => c.id === msg.candidate!.id);
          if (exists) return prev.map((c) => c.id === msg.candidate!.id ? msg.candidate! : c);
          return [msg.candidate!, ...prev];
        });
        updateTask(activeTaskId, {
          discovered: (activeTask?.discovered ?? 0) + 1,
        });
      } else if (msg.type === "complete") {
        updateTask(activeTaskId, { status: "completed", progress: 100 });
      } else if (msg.type === "error") {
        updateTask(activeTaskId, { status: "failed" });
        setError("任务执行出错，请查看任务中心");
      }
    },
    [activeTaskId, activeTask, updateTask]
  );

  useEffect(() => {
    if (!wsEnabled) return;
    on<WsProgressMessage>("message", handleWsMessage);
    return () => off<WsProgressMessage>("message", handleWsMessage);
  }, [wsEnabled, on, off, handleWsMessage]);

  // Load candidates for active task on mount / task change
  useEffect(() => {
    if (!activeTaskId) return;
    getMiningTaskDetail(activeTaskId)
      .then((detail) => {
        setCandidates(detail.candidates ?? []);
        if (detail.evolution_history) setEvolutionHistory(detail.evolution_history);
        if (detail.generation !== undefined) setCurrentGeneration(detail.generation);
        if (detail.total_generations !== undefined) setTotalGenerations(detail.total_generations);
        if (detail.best_fitness !== undefined) setBestFitness(detail.best_fitness);
      })
      .catch(() => {/* task not found yet, ignore */});
  }, [activeTaskId]);

  // Handlers
  async function handleStartGP(config: GPConfig) {
    setSubmitting(true);
    setError(null);
    setEvolutionHistory([]);
    setCandidates([]);
    try {
      const { task_id } = await startGPMining(config);
      upsertTask({
        taskId: task_id,
        engine: "gp",
        status: "running",
        progress: 0,
        discovered: 0,
        passed: 0,
        startedAt: new Date().toISOString(),
        totalGenerations: config.max_generations,
      });
      setActiveTask(task_id);
      setTotalGenerations(config.max_generations);
    } catch (e: unknown) {
      setError((e as Error).message ?? "启动GP任务失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStartLLM(config: LLMConfig) {
    setSubmitting(true);
    setError(null);
    setCandidates([]);
    try {
      const { task_id } = await startLLMMining(config);
      upsertTask({
        taskId: task_id,
        engine: "llm",
        status: "running",
        progress: 0,
        discovered: 0,
        passed: 0,
        startedAt: new Date().toISOString(),
      });
      setActiveTask(task_id);
    } catch (e: unknown) {
      setError((e as Error).message ?? "启动LLM任务失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStartBrute(config: BruteForceConfig) {
    setSubmitting(true);
    setError(null);
    setCandidates([]);
    try {
      const { task_id } = await startBruteForceMining(config);
      upsertTask({
        taskId: task_id,
        engine: "bruteforce",
        status: "running",
        progress: 0,
        discovered: 0,
        passed: 0,
        startedAt: new Date().toISOString(),
      });
      setActiveTask(task_id);
    } catch (e: unknown) {
      setError((e as Error).message ?? "启动枚举任务失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmitGate(ids: string[]) {
    setGateSubmitting(true);
    try {
      // Gate评估需要DSL表达式，从候选因子中提取
      const gatePayloads = candidates
        .filter((c) => ids.includes(c.id))
        .map((c) => ({ expr: c.expression, name: c.name }));
      await submitCandidatesToGate(gatePayloads);
      setCandidates((prev) =>
        prev.map((c) => ids.includes(c.id) ? { ...c, gate_status: "pending" as const } : c)
      );
    } catch (e: unknown) {
      setError((e as Error).message ?? "提交Gate失败");
    } finally {
      setGateSubmitting(false);
    }
  }

  const engineLabel: Record<MiningEngine, string> = { gp: "GP", llm: "LLM", bruteforce: "枚举" };

  return (
    <div>
      <Breadcrumb items={[{ label: "因子挖掘", path: "/mining" }, { label: "因子实验室" }]} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">因子实验室</h1>
          <p className="text-sm text-slate-400 mt-0.5">3种挖掘模式 · 候选因子一键Gate验证</p>
        </div>
        {activeTask && (
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">
              当前任务: <span className="text-slate-300 font-mono">{activeTaskId?.slice(0, 8)}...</span>
            </span>
            <span
              className={[
                "px-2 py-0.5 rounded-full text-[10px] font-medium border",
                activeTask.status === "running"
                  ? "bg-blue-900/60 text-blue-400 border-blue-500/30"
                  : activeTask.status === "completed"
                  ? "bg-green-900/60 text-green-400 border-green-500/30"
                  : activeTask.status === "failed"
                  ? "bg-red-900/60 text-red-400 border-red-500/30"
                  : "bg-slate-700 text-slate-300 border-white/10",
              ].join(" ")}
            >
              {engineLabel[activeTask.engine]} · {activeTask.status}
            </span>
          </div>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 flex items-center justify-between px-4 py-2.5 rounded-xl bg-red-900/30 border border-red-500/30 text-red-300 text-sm">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200 ml-4">✕</button>
        </div>
      )}

      {/* Mode tabs */}
      <div className="flex gap-2 mb-6">
        {MODE_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveMode(tab.key)}
            className={[
              "px-4 py-2.5 rounded-xl border text-xs transition-all text-left",
              activeMode === tab.key
                ? "bg-blue-600/20 border-blue-500/40 text-blue-300"
                : "bg-transparent border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-200",
            ].join(" ")}
          >
            <div className="font-semibold">{tab.label}</div>
            <div className="text-[10px] opacity-70 mt-0.5">{tab.desc}</div>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-4">
        {/* Left: mode panel */}
        <div className="flex flex-col gap-4">
          {activeMode === "gp" && (
            <GPPanel
              onStart={handleStartGP}
              isRunning={isRunning}
              isPaused={isPaused}
              submitting={submitting}
              evolutionHistory={evolutionHistory}
              currentGeneration={currentGeneration}
              totalGenerations={totalGenerations}
              bestFitness={bestFitness}
              completedTaskIds={Object.values(tasks)
                .filter((t) => t.status === "completed" && t.engine === "gp")
                .map((t) => t.taskId)}
            />
          )}
          {activeMode === "llm" && (
            <LLMPanel
              onStart={handleStartLLM}
              isRunning={isRunning}
              submitting={submitting}
            />
          )}
          {activeMode === "bruteforce" && (
            <BruteForcePanel
              onStart={handleStartBrute}
              isRunning={isRunning}
              submitting={submitting}
            />
          )}

          {/* Candidate table */}
          <GlassCard>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-slate-200">候选因子</h3>
              {activeTask && (
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span>
                    发现 <span className="text-slate-200 font-medium">{activeTask.discovered}</span>
                  </span>
                  <span>
                    通过 <span className="text-green-400 font-medium">{activeTask.passed}</span>
                  </span>
                  {activeTask.progress > 0 && activeTask.status === "running" && (
                    <div className="flex items-center gap-1.5">
                      <div className="w-20 bg-slate-800 rounded-full h-1">
                        <div
                          className="bg-blue-500 h-1 rounded-full transition-all"
                          style={{ width: `${activeTask.progress}%` }}
                        />
                      </div>
                      <span>{activeTask.progress}%</span>
                    </div>
                  )}
                </div>
              )}
            </div>
            <CandidateTable
              candidates={candidates}
              onSubmitGate={handleSubmitGate}
              submitting={gateSubmitting}
            />
          </GlassCard>
        </div>

        {/* Right: AI assistant panel */}
        <div className="w-full xl:w-[340px]">
          <GlassCard className="h-full">
            <h3 className="text-sm font-semibold text-slate-200 mb-3">AI 助手</h3>
            <div className="flex flex-col gap-2 mb-4">
              {["生成因子建议", "解释现有因子", "优化建议", "诊断IC衰退"].map((action) => (
                <Button key={action} variant="ghost" size="sm" className="justify-start text-left w-full">
                  {action}
                </Button>
              ))}
            </div>
            <div className="flex flex-col gap-2 flex-1 min-h-[200px] bg-slate-900/40 rounded-xl p-3 border border-white/5">
              <div className="flex-1 flex items-center justify-center">
                <p className="text-xs text-slate-500 text-center">
                  输入问题或选择上方快捷操作<br />
                  <span className="text-[10px] text-slate-600">API: POST /api/ai/factor-assist</span>
                </p>
              </div>
            </div>
            <div className="flex gap-2 mt-3">
              <input
                type="text"
                placeholder="输入问题..."
                className="flex-1 bg-slate-800 border border-white/10 text-slate-200 text-xs rounded-xl px-3 py-2 placeholder:text-slate-600 focus:outline-none focus:border-blue-500/50"
              />
              <Button size="sm" variant="primary">发送</Button>
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
