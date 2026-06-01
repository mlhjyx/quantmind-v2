import { useState, useCallback, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { FactorPanel } from "@/components/strategy/FactorPanel";
import { StrategyEditor } from "@/components/strategy/StrategyEditor";
import { StrategyPreview } from "@/components/strategy/StrategyPreview";
import { AssistPanel } from "@/components/ai/AssistPanel";
import { useNotificationStore } from "@/store/notificationStore";
import { getFactorsSummary } from "@/api/factors";
import {
  createStrategy,
  getStrategy,
  getStrategyFactors,
  getStrategyVersions,
  listStrategies,
  updateStrategy,
} from "@/api/strategies";
import { STALE } from "@/api/QueryProvider";
import { queryKeys } from "@/lib/queryKeys";
import type {
  Strategy,
  StrategyConfigVersion,
  StrategyCreatePayload,
  StrategyFactorsResponse,
} from "@/api/strategies";

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

function strategyToPayload(strategy: Strategy): StrategyCreatePayload {
  return {
    name: strategy.name,
    description: strategy.description ?? "",
    factor_ids: strategy.factor_ids,
    top_n: strategy.top_n,
    rebalance_freq: strategy.rebalance_freq,
    weight_method: strategy.weight_method,
    industry_cap: strategy.industry_cap,
    single_stock_cap: strategy.single_stock_cap,
    initial_capital: strategy.initial_capital,
  };
}

function StrategyMetadataPanel({
  versions,
  factors,
  loading,
}: {
  versions: StrategyConfigVersion[];
  factors?: StrategyFactorsResponse;
  loading: boolean;
}) {
  const latest = versions[0];
  const factorRows = factors?.factors ?? [];

  return (
    <GlassCard padding="sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-200">版本与因子</h3>
        {loading && <span className="text-xs text-slate-500">加载中</span>}
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="px-2.5 py-2 rounded-lg bg-white/5 border border-white/5">
          <p className="text-xs text-slate-500">版本数</p>
          <p className="text-base font-semibold text-slate-200">{versions.length}</p>
        </div>
        <div className="px-2.5 py-2 rounded-lg bg-white/5 border border-white/5">
          <p className="text-xs text-slate-500">因子数</p>
          <p className="text-base font-semibold text-slate-200">
            {factors?.factor_names.length ?? factorRows.length}
          </p>
        </div>
      </div>

      {latest ? (
        <div className="mb-3 text-xs text-slate-400">
          <span className="text-slate-500">最新版本</span>
          <span className="ml-2 text-slate-200">v{latest.version}</span>
          {latest.changelog && <p className="mt-1 line-clamp-2">{latest.changelog}</p>}
        </div>
      ) : (
        <p className="mb-3 text-xs text-slate-500">暂无版本记录</p>
      )}

      {factorRows.length > 0 ? (
        <div className="space-y-1.5">
          {factorRows.slice(0, 5).map((factor) => (
            <div key={factor.name} className="flex items-center justify-between gap-2">
              <span className="text-xs text-slate-300 truncate">{factor.name}</span>
              <span className="text-xs text-slate-500 shrink-0">
                {factor.direction === -1 ? "反向" : factor.direction === 1 ? "正向" : "待补"}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500">未返回因子明细</p>
      )}
    </GlassCard>
  );
}

export default function StrategyWorkspace() {
  const navigate = useNavigate();
  const { id: routeStrategyId } = useParams<{ id?: string }>();
  const queryClient = useQueryClient();
  const routeEditId = routeStrategyId && routeStrategyId !== "new" ? routeStrategyId : null;

  const [config, setConfig] = useState<StrategyCreatePayload>(DEFAULT_CONFIG);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loadPanelOpen, setLoadPanelOpen] = useState(false);

  // Fetch factors
  const { data: factors = [], isError: factorsError } = useQuery({
    queryKey: [...queryKeys.factorsSummary],
    queryFn: getFactorsSummary,
    staleTime: STALE.factor,
    retry: 1,
  });

  // Fetch saved strategies for load panel
  const { data: strategies = [] } = useQuery({
    queryKey: [...queryKeys.strategies],
    queryFn: listStrategies,
    staleTime: STALE.config,
    enabled: loadPanelOpen,
    retry: false,
  });

  const {
    data: routeStrategy,
    isFetching: strategyDetailLoading,
    isError: strategyDetailError,
  } = useQuery({
    queryKey: routeEditId ? [...queryKeys.strategyDetail(routeEditId)] : ["strategies", "new"],
    queryFn: () => getStrategy(routeEditId!),
    enabled: Boolean(routeEditId),
    staleTime: STALE.config,
    retry: false,
  });

  const metadataStrategyId = editingId ?? routeEditId;
  const { data: strategyVersions = [], isFetching: versionsLoading } = useQuery({
    queryKey: metadataStrategyId
      ? [...queryKeys.strategyVersions(metadataStrategyId)]
      : ["strategies", "versions", "idle"],
    queryFn: () => getStrategyVersions(metadataStrategyId!),
    enabled: Boolean(metadataStrategyId),
    staleTime: STALE.config,
    retry: false,
  });

  const { data: strategyFactors, isFetching: factorsLoading } = useQuery({
    queryKey: metadataStrategyId
      ? [...queryKeys.strategyFactors(metadataStrategyId)]
      : ["strategies", "factors", "idle"],
    queryFn: () => getStrategyFactors(metadataStrategyId!),
    enabled: Boolean(metadataStrategyId),
    staleTime: STALE.factor,
    retry: false,
  });

  useEffect(() => {
    if (!routeEditId) {
      setConfig(DEFAULT_CONFIG);
      setEditingId(null);
    }
  }, [routeEditId]);

  useEffect(() => {
    if (!routeStrategy) return;
    setConfig(strategyToPayload(routeStrategy));
    setEditingId(routeStrategy.id);
  }, [routeStrategy]);

  const saveMutation = useMutation({
    mutationFn: () =>
      editingId
        ? updateStrategy(editingId, config)
        : createStrategy(config),
    onSuccess: (saved: Strategy) => {
      setEditingId(saved.id);
      queryClient.invalidateQueries({ queryKey: [...queryKeys.strategies] });
      queryClient.invalidateQueries({ queryKey: [...queryKeys.strategyDetail(saved.id)] });
      if (saved.id && saved.id !== routeEditId) {
        navigate(`/strategy/${saved.id}`, { replace: !editingId });
      }
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
      useNotificationStore.getState().add({
        type: "warning",
        title: "请输入策略名称",
        message: "策略名称不能为空",
      });
      return;
    }
    saveMutation.mutate();
  };

  const handleRunBacktest = () => {
    if (!config.name.trim()) {
      useNotificationStore.getState().add({
        type: "warning",
        title: "请先保存策略",
        message: "运行回测前必须保存策略",
      });
      return;
    }
    if (!editingId) {
      useNotificationStore.getState().add({
        type: "warning",
        title: "请先保存策略",
        message: "回测配置需要已保存的策略ID",
      });
      return;
    }
    navigate(`/backtest/config?strategy_id=${editingId}`);
  };

  const handleLoadStrategy = (s: Strategy) => {
    setConfig(strategyToPayload(s));
    setEditingId(s.id);
    setLoadPanelOpen(false);
    navigate(`/strategy/${s.id}`);
  };

  return (
    <div className="h-full flex flex-col">
      <Breadcrumb items={[{ label: "策略工作台" }]} />

      {factorsError && (
        <ErrorBanner message="因子数据加载失败，请确认后端API已启动" className="mb-3" />
      )}
      {strategyDetailError && (
        <ErrorBanner message="策略详情加载失败，请返回策略库重新选择" className="mb-3" />
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
              navigate("/strategy/new");
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
          {/* AI Assistant — Frontend Design v3 §3.2.2 (replaces Sprint 1.18 placeholder) */}
          <AssistPanel context={{ page: "strategy" }} mode="inline" />

          <StrategyMetadataPanel
            versions={strategyVersions}
            factors={strategyFactors}
            loading={strategyDetailLoading || versionsLoading || factorsLoading}
          />

          {/* Strategy Preview */}
          <GlassCard className="flex-1 overflow-y-auto" padding="sm">
            <StrategyPreview config={config} allFactors={factors} />
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
