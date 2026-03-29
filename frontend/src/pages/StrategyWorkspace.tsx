import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { FactorPanel } from "@/components/strategy/FactorPanel";
import { StrategyEditor } from "@/components/strategy/StrategyEditor";
import { StrategyPreview } from "@/components/strategy/StrategyPreview";
import { getFactorsSummary } from "@/api/factors";
import { listStrategies, createStrategy, updateStrategy } from "@/api/strategies";
import { STALE } from "@/api/QueryProvider";
import type { StrategyCreatePayload, Strategy } from "@/api/strategies";

const DEFAULT_CONFIG: StrategyCreatePayload = {
  name: "",
  description: "",
  factor_ids: [],
  top_n: 15,
  rebalance_freq: "monthly",
  weight_method: "equal",
  industry_cap: 0.25,
  single_stock_cap: 0.1,
  initial_capital: 1_000_000,
};

import { ErrorBanner } from "@/components/ui/ErrorBanner";

export default function StrategyWorkspace() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [config, setConfig] = useState<StrategyCreatePayload>(DEFAULT_CONFIG);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loadPanelOpen, setLoadPanelOpen] = useState(false);

  // Fetch factors
  const { data: factors = [], isError: factorsError } = useQuery({
    queryKey: ["factors", "summary"],
    queryFn: getFactorsSummary,
    staleTime: STALE.factor,
    retry: 1,
  });

  // Fetch saved strategies for load panel
  const { data: strategies = [] } = useQuery({
    queryKey: ["strategies"],
    queryFn: listStrategies,
    staleTime: STALE.config,
    enabled: loadPanelOpen,
    retry: false,
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      editingId
        ? updateStrategy(editingId, config)
        : createStrategy(config),
    onSuccess: (saved: Strategy) => {
      setEditingId(saved.id);
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
  });

  const handleConfigChange = useCallback((updates: Partial<StrategyCreatePayload>) => {
    setConfig((prev) => ({ ...prev, ...updates }));
  }, []);

  const handleFactorChange = useCallback((ids: string[]) => {
    setConfig((prev) => ({ ...prev, factor_ids: ids }));
  }, []);

  const handleSave = () => {
    if (!config.name.trim()) {
      alert("请输入策略名称");
      return;
    }
    saveMutation.mutate();
  };

  const handleRunBacktest = () => {
    if (!config.name.trim()) {
      alert("请先保存策略");
      return;
    }
    navigate("/backtest/config");
  };

  const handleLoadStrategy = (s: Strategy) => {
    setConfig({
      name: s.name,
      description: s.description ?? "",
      factor_ids: s.factor_ids,
      top_n: s.top_n,
      rebalance_freq: s.rebalance_freq,
      weight_method: s.weight_method,
      industry_cap: s.industry_cap,
      single_stock_cap: s.single_stock_cap,
      initial_capital: s.initial_capital,
    });
    setEditingId(s.id);
    setLoadPanelOpen(false);
  };

  return (
    <div className="h-full flex flex-col">
      <Breadcrumb items={[{ label: "策略工作台" }]} />

      {factorsError && (
        <ErrorBanner message="因子数据加载失败，请确认后端API已启动" className="mb-3" />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-white">策略工作台</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {editingId ? `编辑中: ${config.name}` : "新建策略"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setLoadPanelOpen(!loadPanelOpen)}
          >
            加载策略
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setConfig(DEFAULT_CONFIG);
              setEditingId(null);
            }}
          >
            新建
          </Button>
        </div>
      </div>

      {/* Load strategy panel */}
      {loadPanelOpen && (
        <GlassCard className="mb-4" padding="sm">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-slate-200">策略库</h3>
            <button
              onClick={() => setLoadPanelOpen(false)}
              className="text-slate-500 hover:text-slate-300 text-sm"
            >
              ✕
            </button>
          </div>
          {strategies.length === 0 ? (
            <p className="text-xs text-slate-500 py-2">暂无保存的策略</p>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {strategies.map((s) => (
                <GlassCard
                  key={s.id}
                  variant="clickable"
                  padding="sm"
                  onClick={() => handleLoadStrategy(s)}
                >
                  <p className="text-xs font-medium text-slate-200 truncate">{s.name}</p>
                  <div className="flex gap-3 mt-1 text-xs text-slate-500">
                    {s.sharpe !== undefined && <span>Sharpe {s.sharpe.toFixed(2)}</span>}
                    {s.mdd !== undefined && <span>MDD {(s.mdd * 100).toFixed(1)}%</span>}
                    <span>{s.factor_ids.length}因子</span>
                  </div>
                </GlassCard>
              ))}
            </div>
          )}
        </GlassCard>
      )}

      {/* Three-column layout */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Left: Factor Panel (200px) */}
        <GlassCard className="w-[220px] shrink-0 flex flex-col" padding="sm">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">因子面板</h2>
          <div className="flex-1 min-h-0">
            <FactorPanel
              factors={factors}
              selectedIds={config.factor_ids}
              onChange={handleFactorChange}
            />
          </div>
        </GlassCard>

        {/* Center: Strategy Editor (flex-1) */}
        <GlassCard className="flex-1 flex flex-col min-w-0" padding="md">
          <StrategyEditor
            value={config}
            onChange={handleConfigChange}
            onSave={handleSave}
            onRunBacktest={handleRunBacktest}
            saving={saveMutation.isPending}
          />

          {/* Save feedback */}
          {saveMutation.isSuccess && (
            <div className="mt-3 px-3 py-2 rounded-xl bg-green-500/10 border border-green-500/20">
              <p className="text-xs text-green-400">策略已保存</p>
            </div>
          )}
          {saveMutation.isError && (
            <div className="mt-3 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20">
              <p className="text-xs text-red-400">保存失败，请重试</p>
            </div>
          )}
        </GlassCard>

        {/* Right: AI Assistant + Preview (260px) */}
        <div className="w-[260px] shrink-0 flex flex-col gap-4">
          {/* AI Assistant placeholder */}
          <GlassCard variant="glow" padding="sm">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-base">🤖</span>
              <h2 className="text-xs font-semibold text-slate-300">AI 助手</h2>
              <span className="ml-auto text-xs text-slate-600 bg-slate-700/50 px-1.5 py-0.5 rounded">Sprint 1.18</span>
            </div>
            <div className="space-y-2 mb-3">
              {["生成策略", "优化建议", "解释策略", "因子诊断"].map((label) => (
                <button
                  key={label}
                  disabled
                  className="w-full text-left px-3 py-1.5 rounded-lg text-xs text-slate-500 border border-white/5 cursor-not-allowed opacity-60"
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/5">
              <p className="text-xs text-slate-600 italic">AI 策略助手即将上线</p>
            </div>
          </GlassCard>

          {/* Strategy Preview */}
          <GlassCard className="flex-1 overflow-y-auto" padding="sm">
            <StrategyPreview config={config} allFactors={factors} />
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
