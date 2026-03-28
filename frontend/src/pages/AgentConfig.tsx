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
  type AgentConfig as AgentConfigType,
  type AgentName,
  type ModelHealth as ModelHealthType,
  type CostSummary,
} from "@/api/agent";

const AGENT_TABS: { id: AgentName; label: string; icon: string; desc: string }[] = [
  { id: "idea",      label: "Idea Agent",      icon: "💡", desc: "因子发现与假设生成" },
  { id: "factor",    label: "Factor Agent",     icon: "🧬", desc: "因子评估与筛选" },
  { id: "eval",      label: "Eval Agent",       icon: "📊", desc: "策略评估与验证" },
  { id: "diagnosis", label: "Diagnosis Agent",  icon: "🩺", desc: "诊断优化与修复" },
];

const PAGE_TABS = ["Agent配置", "模型健康", "费用仪表盘"] as const;
type PageTab = (typeof PAGE_TABS)[number];

export default function AgentConfig() {
  const [activeAgent, setActiveAgent] = useState<AgentName>("idea");
  const [activePageTab, setActivePageTab] = useState<PageTab>("Agent配置");
  const [configs, setConfigs] = useState<AgentConfigType[]>([]);
  const [modelHealth, setModelHealth] = useState<ModelHealthType[]>([]);
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null);
  const [loadingConfigs, setLoadingConfigs] = useState(true);
  const [loadingHealth, setLoadingHealth] = useState(false);
  const [loadingCost, setLoadingCost] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  useEffect(() => {
    if (activePageTab === "模型健康") loadModelHealth();
    else if (activePageTab === "费用仪表盘") loadCostSummary();
  }, [activePageTab, loadModelHealth, loadCostSummary]);

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
          >
            恢复默认
          </Button>
          <Button
            size="sm"
            loading={saving}
            disabled={!hasUnsavedChanges}
            onClick={handleSave}
            className={saveSuccess ? "bg-green-600 border-green-500/50" : ""}
          >
            {saveSuccess ? "已保存 ✓" : "保存配置"}
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
    </div>
  );
}
