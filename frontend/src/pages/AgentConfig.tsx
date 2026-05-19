import { useState, useEffect, useCallback } from "react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { Button } from "@/components/ui/Button";
import { AgentTab } from "@/components/agent/AgentTab";
import { ModelHealth } from "@/components/agent/ModelHealth";
import { CostDashboard } from "@/components/agent/CostDashboard";
import {
  getAllAgentConfigs,
  getModelHealth,
  getCostSummary,
  updateAgentConfig,
  resetAgentConfig,
  getAgentHistory,
  rollbackAgentConfig,
  type AgentConfig as AgentConfigType,
  type AgentName,
  type AgentHistoryRow,
  type ModelHealth as ModelHealthType,
  type CostSummary,
} from "@/api/agent";
import { ConfirmModal } from "@/components/ui/ConfirmModal";

const AGENT_TABS: { id: AgentName; label: string; icon: string; desc: string }[] = [
  { id: "idea",      label: "Idea Agent",      icon: "💡", desc: "因子发现与假设生成" },
  { id: "factor",    label: "Factor Agent",     icon: "🧬", desc: "因子评估与筛选" },
  { id: "eval",      label: "Eval Agent",       icon: "📊", desc: "策略评估与验证" },
  { id: "diagnosis", label: "Diagnosis Agent",  icon: "🩺", desc: "诊断优化与修复" },
];

const PAGE_TABS = ["Agent配置", "Prompt 版本", "模型健康", "费用仪表盘"] as const;
type PageTab = (typeof PAGE_TABS)[number];

export default function AgentConfig() {
  const [activeAgent, setActiveAgent] = useState<AgentName>("idea");
  const [activePageTab, setActivePageTab] = useState<PageTab>("Agent配置");
  const [configs, setConfigs] = useState<AgentConfigType[]>([]);
  const [modelHealth, setModelHealth] = useState<ModelHealthType[]>([]);
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null);
  const [history, setHistory] = useState<AgentHistoryRow[]>([]);
  const [loadingConfigs, setLoadingConfigs] = useState(true);
  const [loadingHealth, setLoadingHealth] = useState(false);
  const [loadingCost, setLoadingCost] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // H1 真闭环 (2026-05-19): prompt_history table 已 land (migration 2026_05_19), save 真持久化
  const [saveSuccess, setSaveSuccess] = useState(false);
  // Track per-agent local changes
  const [localChanges, setLocalChanges] = useState<Record<AgentName, Partial<AgentConfigType>>>({
    idea: {}, factor: {}, eval: {}, diagnosis: {},
  });

  const loadConfigs = useCallback(async () => {
    setLoadingConfigs(true);
    try {
      const data = await getAllAgentConfigs();
      setConfigs(data);
      setError(null);
    } catch {
      setError("无法加载 Agent 配置，请检查后端连接");
    } finally {
      setLoadingConfigs(false);
    }
  }, []);

  const loadModelHealth = useCallback(async () => {
    setLoadingHealth(true);
    try {
      const data = await getModelHealth();
      setModelHealth(data);
    } catch {
      // silent
    } finally {
      setLoadingHealth(false);
    }
  }, []);

  const loadCostSummary = useCallback(async () => {
    setLoadingCost(true);
    try {
      const data = await getCostSummary();
      setCostSummary(data);
    } catch {
      // silent
    } finally {
      setLoadingCost(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const rows = await getAgentHistory(activeAgent, 50);
      setHistory(rows);
    } catch {
      setHistory([]);
    } finally {
      setLoadingHistory(false);
    }
  }, [activeAgent]);

  const handleRollback = async (version: number) => {
    setRollbackTarget(null);
    try {
      const updated = await rollbackAgentConfig(
        activeAgent,
        version,
        `rollback via UI to v${version}`,
      );
      setConfigs((prev) => prev.map((c) => (c.name === activeAgent ? updated : c)));
      // Refresh history
      await loadHistory();
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "rollback 失败";
      setError(`回滚失败: ${msg}`);
    }
  };

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  useEffect(() => {
    if (activePageTab === "模型健康") loadModelHealth();
    else if (activePageTab === "费用仪表盘") loadCostSummary();
    else if (activePageTab === "Prompt 版本") loadHistory();
  }, [activePageTab, loadModelHealth, loadCostSummary, loadHistory]);

  const currentConfig = configs.find((c) => c.name === activeAgent);
  const mergedConfig = currentConfig
    ? { ...currentConfig, ...localChanges[activeAgent] }
    : null;

  const handleChange = (updates: Partial<AgentConfigType>) => {
    setLocalChanges((prev) => ({
      ...prev,
      [activeAgent]: { ...prev[activeAgent], ...updates },
    }));
  };

  const handleSave = async () => {
    const changes = localChanges[activeAgent];
    if (Object.keys(changes).length === 0) return;
    setSaving(true);
    try {
      const updated = await updateAgentConfig(activeAgent, changes);
      setConfigs((prev) => prev.map((c) => (c.name === activeAgent ? updated : c)));
      setLocalChanges((prev) => ({ ...prev, [activeAgent]: {} }));
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
      setError(null);
    } catch {
      setError("保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    try {
      const defaultConfig = await resetAgentConfig(activeAgent);
      setConfigs((prev) => prev.map((c) => (c.name === activeAgent ? defaultConfig : c)));
      setLocalChanges((prev) => ({ ...prev, [activeAgent]: {} }));
      setError(null);
    } catch {
      setError("恢复默认失败");
    } finally {
      setResetting(false);
    }
  };

  const hasUnsavedChanges = Object.keys(localChanges[activeAgent]).length > 0;

  return (
    <div>
      <Breadcrumb
        items={[{ label: "AI闭环", path: "/pipeline" }, { label: "Agent配置" }]}
      />

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Agent 配置</h1>
          <p className="text-sm text-slate-400 mt-0.5">4个 Agent 模型选择与决策阈值</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            loading={resetting}
            onClick={handleReset}
            title="重置为 default config (新 version row INSERT)"
          >
            恢复默认
          </Button>
          <Button
            size="sm"
            loading={saving}
            disabled={!hasUnsavedChanges}
            onClick={handleSave}
            className={saveSuccess ? "bg-green-600 border-green-500/50" : ""}
            title="保存为新 version row (prompt_history table)"
          >
            {saveSuccess ? "已保存 ✓" : "保存配置"}
          </Button>
        </div>
      </div>

      {/* H1 真闭环 (2026-05-19): prompt_history table 已 land, 真 persist 启用. */}
      <div className="mb-4 flex items-start gap-2 bg-emerald-900/20 border border-emerald-500/30 rounded-xl px-4 py-3">
        <span className="text-emerald-400 text-base shrink-0">✓</span>
        <div className="flex-1">
          <div className="text-sm text-emerald-200 font-semibold mb-1">
            Prompt Versioning Active — 配置改动真持久化 (prompt_history table)
          </div>
          <div className="text-xs text-slate-300 leading-relaxed">
            点击 <strong>保存配置</strong> 触发 PUT /api/agent/{`{name}`}/config — backend 真
            INSERT 新 version row + mark 前 active=FALSE (atomic txn). GET /history 可拉
            last N versions. Rollback / version diff UI 留 Phase I 续期 enhancement.
            详 <code className="text-emerald-200">backend/migrations/2026_05_19_prompt_history.sql</code>.
          </div>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 flex items-center justify-between bg-red-900/30 border border-red-500/30 rounded-xl px-4 py-2.5">
          <span className="text-sm text-red-300">{error}</span>
          <button className="text-xs text-red-400 hover:text-red-200" onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* Page tabs */}
      <div className="flex gap-1 mb-5 border-b border-white/5 pb-1">
        {PAGE_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActivePageTab(tab)}
            className={[
              "px-4 py-2 text-xs font-medium rounded-t-lg transition-colors duration-150",
              activePageTab === tab
                ? "text-blue-300 bg-blue-500/10"
                : "text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {tab}
          </button>
        ))}
      </div>

      {activePageTab === "Agent配置" && (
        <div className="flex gap-4">
          {/* Agent selector sidebar */}
          <div className="w-48 shrink-0 space-y-1">
            {AGENT_TABS.map(({ id, label, icon, desc }) => {
              const active = activeAgent === id;
              const hasChanges = Object.keys(localChanges[id]).length > 0;
              return (
                <button
                  key={id}
                  onClick={() => setActiveAgent(id)}
                  className={[
                    "w-full text-left px-3 py-3 rounded-xl border transition-all duration-150",
                    active
                      ? "border-blue-500/50 bg-blue-900/30 shadow-[0_0_10px_rgba(96,165,250,0.15)]"
                      : "border-white/10 bg-slate-800/30 hover:border-white/20",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-base">{icon}</span>
                    <div className="min-w-0">
                      <p className={`text-xs font-semibold ${active ? "text-blue-300" : "text-slate-300"}`}>
                        {label}
                      </p>
                      <p className="text-[10px] text-slate-500 truncate">{desc}</p>
                    </div>
                    {hasChanges && (
                      <span className="ml-auto w-1.5 h-1.5 rounded-full bg-yellow-400 shrink-0" />
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Config panel */}
          <div className="flex-1 min-w-0">
            {loadingConfigs ? (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-40 rounded-2xl bg-slate-800/40 animate-pulse" />
                ))}
              </div>
            ) : mergedConfig ? (
              <>
                {hasUnsavedChanges && (
                  <div className="mb-3 flex items-center gap-2 bg-yellow-900/20 border border-yellow-500/20 rounded-xl px-4 py-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
                    <span className="text-xs text-yellow-300">有未保存的更改</span>
                  </div>
                )}
                <AgentTab config={mergedConfig} onChange={handleChange} />
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <span className="text-4xl mb-3">⚙️</span>
                <p className="text-sm text-slate-400">无法加载配置</p>
                <Button size="sm" variant="secondary" className="mt-3" onClick={loadConfigs}>
                  重试
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {activePageTab === "Prompt 版本" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">
              {activeAgent} agent · prompt_history version chain (active row highlighted)
            </p>
            <Button size="sm" variant="ghost" onClick={loadHistory} disabled={loadingHistory}>
              {loadingHistory ? "加载中..." : "刷新"}
            </Button>
          </div>
          {loadingHistory && history.length === 0 ? (
            <div className="text-center py-8 text-sm text-slate-400">加载中...</div>
          ) : history.length === 0 ? (
            <div className="text-center py-8 text-sm text-slate-500">
              暂无版本历史 (首次使用会自动 seed v1)
            </div>
          ) : (
            <div className="space-y-2">
              {history.map((row) => (
                <div
                  key={row.version}
                  className={`px-4 py-3 rounded-xl border ${
                    row.is_active
                      ? "bg-emerald-500/10 border-emerald-500/40"
                      : "bg-slate-800/40 border-slate-700"
                  }`}
                >
                  <div className="flex items-center gap-3 mb-2">
                    <span
                      className={`text-sm font-mono font-semibold ${
                        row.is_active ? "text-emerald-300" : "text-slate-300"
                      }`}
                    >
                      v{row.version}
                    </span>
                    {row.is_active && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300">
                        ACTIVE
                      </span>
                    )}
                    <span className="text-xs text-slate-500 font-mono">{row.model}</span>
                    <span className="text-xs text-slate-500">temp={row.temperature.toFixed(2)}</span>
                    <span className="text-xs text-slate-500">max_tokens={row.max_tokens}</span>
                    <div className="ml-auto flex items-center gap-2">
                      <span className="text-xs text-slate-500 font-mono">
                        {row.created_at?.slice(0, 19).replace("T", " ") ?? "—"}
                      </span>
                      {!row.is_active && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setRollbackTarget(row.version)}
                          title={`回滚到 v${row.version} (INSERT 新 version 复制此 row)`}
                        >
                          回滚至此
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="flex-1">
                      <p className="text-xs text-slate-500 mb-1">理由 / 创建者</p>
                      <p className="text-xs text-slate-300">
                        {row.reason ?? "—"}{" "}
                        <span className="text-slate-500">· by {row.created_by}</span>
                      </p>
                    </div>
                  </div>
                  <details className="mt-2">
                    <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-300">
                      System prompt ({row.system_prompt.length} chars)
                    </summary>
                    <pre className="mt-2 p-2 bg-slate-900/60 rounded text-xs text-slate-300 whitespace-pre-wrap font-mono overflow-x-auto max-h-40">
                      {row.system_prompt}
                    </pre>
                  </details>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activePageTab === "模型健康" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">API 连通性 · 响应延迟</p>
            <Button size="sm" variant="ghost" onClick={loadModelHealth} disabled={loadingHealth}>
              {loadingHealth ? "检测中..." : "重新检测"}
            </Button>
          </div>
          <ModelHealth models={modelHealth} loading={loadingHealth} />
        </div>
      )}

      {activePageTab === "费用仪表盘" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">月度 Token 使用量与费用统计</p>
            <Button size="sm" variant="ghost" onClick={loadCostSummary} disabled={loadingCost}>
              {loadingCost ? "加载中..." : "刷新"}
            </Button>
          </div>
          <CostDashboard summary={costSummary} loading={loadingCost} />
        </div>
      )}

      {rollbackTarget !== null && (
        <ConfirmModal
          title={`回滚 ${activeAgent} 到 v${rollbackTarget}`}
          message={`将 INSERT 新 version row 复制 v${rollbackTarget} 内容 + 当前 active row 标 FALSE. 反 destructive overwrite (旧 version 保留, audit trail real). 请确认.`}
          safetyTier="HIGH"
          requiredReason
          reasonMinLength={5}
          onConfirm={() => void handleRollback(rollbackTarget)}
          onCancel={() => setRollbackTarget(null)}
        />
      )}
    </div>
  );
}
