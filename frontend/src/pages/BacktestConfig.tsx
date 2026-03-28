import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { TabMarket } from "@/components/backtest/TabMarket";
import { TabTimeRange } from "@/components/backtest/TabTimeRange";
import { TabExecution } from "@/components/backtest/TabExecution";
import { TabCostModel } from "@/components/backtest/TabCostModel";
import { TabRiskAdvanced } from "@/components/backtest/TabRiskAdvanced";
import { TabDynamicPosition } from "@/components/backtest/TabDynamicPosition";
import type { MarketConfig } from "@/components/backtest/TabMarket";
import type { TimeRangeConfig } from "@/components/backtest/TabTimeRange";
import type { ExecutionConfig } from "@/components/backtest/TabExecution";
import type { CostModelConfig } from "@/components/backtest/TabCostModel";
import type { RiskAdvancedConfig } from "@/components/backtest/TabRiskAdvanced";
import type { DynamicPositionConfig } from "@/components/backtest/TabDynamicPosition";
import apiClient from "@/api/client";

// ── Default config values ──────────────────────────────────────────────────

const DEFAULT_MARKET: MarketConfig = {
  market: "astock",
  universe: "all",
  industries: [],
  custom_stocks: "",
  estimated_count: 5000,
};

const DEFAULT_TIME_RANGE: TimeRangeConfig = {
  start_date: "2021-03-01",
  end_date: "2026-03-28",
  preset: "5y",
  exclude_2015: false,
  exclude_2020: false,
  exclude_custom: "",
  market_regime_analysis: false,
  regime_method: "ma",
};

const DEFAULT_EXECUTION: ExecutionConfig = {
  fill_price: "next_open",
  rebalance_freq: "monthly",
  signal_day: "",
  holding_count: 15,
  weight_method: "equal",
};

const DEFAULT_COST_MODEL: CostModelConfig = {
  commission_rate: 0.0003,
  stamp_tax: 0.001,
  transfer_fee: 0.00002,
  slippage_model: "fixed",
  slippage_bps: 5,
  volume_impact_coeff: 0.1,
  max_volume_pct: 10,
};

const DEFAULT_RISK_ADVANCED: RiskAdvancedConfig = {
  industry_cap: 0.25,
  single_stock_cap: 0.1,
  unfilled_handling: "next_day",
  walk_forward: false,
  wf_train_months: 24,
  wf_test_months: 6,
  turnover_control: false,
  max_turnover: 0.5,
  round_lot_constraint: true,
  config_template_name: "",
};

const DEFAULT_DYNAMIC_POSITION: DynamicPositionConfig = {
  enabled: false,
  signal_type: "ma_momentum",
  full_position_threshold: 0.5,
  half_position_threshold: 0.0,
  empty_position_threshold: -0.5,
  signal_smooth_days: 5,
};

// ── Tab definition ──────────────────────────────────────────────────────────

type TabKey = "market" | "timerange" | "execution" | "cost" | "risk" | "position";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "market", label: "市场/股票池", icon: "📊" },
  { key: "timerange", label: "时间段", icon: "📅" },
  { key: "execution", label: "执行参数", icon: "⚙️" },
  { key: "cost", label: "成本模型", icon: "💰" },
  { key: "risk", label: "风控/高级", icon: "🛡️" },
  { key: "position", label: "动态仓位", icon: "📈" },
];

// ── Backtest run API ────────────────────────────────────────────────────────

interface BacktestRunPayload {
  market: MarketConfig;
  time_range: TimeRangeConfig;
  execution: ExecutionConfig;
  cost_model: CostModelConfig;
  risk_advanced: RiskAdvancedConfig;
  dynamic_position: DynamicPositionConfig;
}

async function runBacktest(payload: BacktestRunPayload) {
  const res = await apiClient.post<{ run_id: string }>("/backtest/run", payload);
  return res.data;
}

// ── Capital constraint check ────────────────────────────────────────────────

function CapitalWarning({ holding: holdingCount, capital }: { holding: number; capital: number }) {
  const perStock = holdingCount > 0 ? capital / holdingCount : 0;
  const threshold = 200 * 100; // 200元股票最低1手
  if (perStock >= threshold) return null;
  return (
    <div className="flex items-start gap-2 px-4 py-2.5 bg-yellow-500/10 border border-yellow-500/20 rounded-xl">
      <span className="text-yellow-400 shrink-0 mt-0.5">⚠️</span>
      <p className="text-xs text-yellow-300">
        初始资金 ¥{(capital / 10000).toFixed(0)}万 / 持仓{holdingCount}只 = 单只约 ¥{(perStock / 10000).toFixed(2)}万，部分高价股无法买满1手
      </p>
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

export default function BacktestConfig() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>("market");

  const [market, setMarket] = useState<MarketConfig>(DEFAULT_MARKET);
  const [timeRange, setTimeRange] = useState<TimeRangeConfig>(DEFAULT_TIME_RANGE);
  const [execution, setExecution] = useState<ExecutionConfig>(DEFAULT_EXECUTION);
  const [costModel, setCostModel] = useState<CostModelConfig>(DEFAULT_COST_MODEL);
  const [riskAdvanced, setRiskAdvanced] = useState<RiskAdvancedConfig>(DEFAULT_RISK_ADVANCED);
  const [dynamicPosition, setDynamicPosition] = useState<DynamicPositionConfig>(DEFAULT_DYNAMIC_POSITION);

  const updateMarket = useCallback((u: Partial<MarketConfig>) => setMarket((p) => ({ ...p, ...u })), []);
  const updateTimeRange = useCallback((u: Partial<TimeRangeConfig>) => setTimeRange((p) => ({ ...p, ...u })), []);
  const updateExecution = useCallback((u: Partial<ExecutionConfig>) => setExecution((p) => ({ ...p, ...u })), []);
  const updateCostModel = useCallback((u: Partial<CostModelConfig>) => setCostModel((p) => ({ ...p, ...u })), []);
  const updateRiskAdvanced = useCallback((u: Partial<RiskAdvancedConfig>) => setRiskAdvanced((p) => ({ ...p, ...u })), []);
  const updateDynamicPosition = useCallback((u: Partial<DynamicPositionConfig>) => setDynamicPosition((p) => ({ ...p, ...u })), []);

  const runMutation = useMutation({
    mutationFn: () =>
      runBacktest({ market, time_range: timeRange, execution, cost_model: costModel, risk_advanced: riskAdvanced, dynamic_position: dynamicPosition }),
    onSuccess: (data) => {
      navigate(`/backtest/runner/${data.run_id}`);
    },
  });

  function handleReset() {
    setMarket(DEFAULT_MARKET);
    setTimeRange(DEFAULT_TIME_RANGE);
    setExecution(DEFAULT_EXECUTION);
    setCostModel(DEFAULT_COST_MODEL);
    setRiskAdvanced(DEFAULT_RISK_ADVANCED);
    setDynamicPosition(DEFAULT_DYNAMIC_POSITION);
  }

  // Estimated run duration (rough heuristic)
  const dayRange = Math.ceil(
    (new Date(timeRange.end_date).getTime() - new Date(timeRange.start_date).getTime()) / (1000 * 86400)
  );
  const wfMultiplier = riskAdvanced.walk_forward ? 3 : 1;
  const estimatedSeconds = Math.round((dayRange / 365) * 5 * wfMultiplier);
  const estimatedDuration = estimatedSeconds < 60 ? `~${estimatedSeconds}秒` : `~${Math.ceil(estimatedSeconds / 60)}分钟`;

  return (
    <div className="flex flex-col h-full">
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: "回测配置" },
        ]}
      />

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-white">回测配置</h1>
          <p className="text-sm text-slate-400 mt-0.5">配置回测参数，支持6个维度精细控制</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={handleReset}>
            恢复默认
          </Button>
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
            取消
          </Button>
        </div>
      </div>

      {/* Capital warning banner */}
      <div className="mb-4">
        <CapitalWarning holding={execution.holding_count} capital={1_000_000} />
      </div>

      {/* Main card */}
      <GlassCard className="flex-1 flex flex-col min-h-0">
        {/* Tab bar */}
        <div className="flex gap-1 p-1 bg-white/5 rounded-xl mb-6 shrink-0">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 flex-1 justify-center py-2 px-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === tab.key
                  ? "bg-blue-600 text-white shadow-[0_0_10px_rgba(59,130,246,0.3)]"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              }`}
            >
              <span>{tab.icon}</span>
              <span className="hidden md:inline">{tab.label}</span>
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto pr-1">
          {activeTab === "market" && (
            <TabMarket value={market} onChange={updateMarket} />
          )}
          {activeTab === "timerange" && (
            <TabTimeRange value={timeRange} onChange={updateTimeRange} />
          )}
          {activeTab === "execution" && (
            <TabExecution value={execution} onChange={updateExecution} />
          )}
          {activeTab === "cost" && (
            <TabCostModel value={costModel} onChange={updateCostModel} />
          )}
          {activeTab === "risk" && (
            <TabRiskAdvanced
              value={riskAdvanced}
              onChange={updateRiskAdvanced}
              onSaveTemplate={() => {}}
              onLoadTemplate={() => {}}
              onResetDefault={() => setRiskAdvanced(DEFAULT_RISK_ADVANCED)}
              estimatedDuration={estimatedDuration}
            />
          )}
          {activeTab === "position" && (
            <TabDynamicPosition value={dynamicPosition} onChange={updateDynamicPosition} />
          )}
        </div>

        {/* Tab navigation footer */}
        <div className="flex items-center justify-between mt-6 pt-4 border-t border-white/5 shrink-0">
          <div className="flex gap-2">
            {TABS.findIndex((t) => t.key === activeTab) > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  const idx = TABS.findIndex((t) => t.key === activeTab);
                  const prev = TABS[idx - 1];
                  if (prev) setActiveTab(prev.key);
                }}
              >
                ← 上一步
              </Button>
            )}
            {TABS.findIndex((t) => t.key === activeTab) < TABS.length - 1 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  const idx = TABS.findIndex((t) => t.key === activeTab);
                  const next = TABS[idx + 1];
                  if (next) setActiveTab(next.key);
                }}
              >
                下一步 →
              </Button>
            )}
          </div>

          <div className="flex items-center gap-3">
            {runMutation.isError && (
              <span className="text-xs text-red-400">启动失败，请检查配置后重试</span>
            )}
            <span className="text-xs text-slate-500">{estimatedDuration}</span>
            <Button
              size="md"
              onClick={() => runMutation.mutate()}
              loading={runMutation.isPending}
              disabled={runMutation.isPending}
            >
              ▶ 运行回测
            </Button>
          </div>
        </div>
      </GlassCard>

      {/* Config summary strip */}
      <div className="mt-3 flex gap-4 px-4 py-2.5 rounded-xl border border-white/5 bg-white/[0.02] text-xs text-slate-500 flex-wrap">
        <span>
          股票池: <span className="text-slate-300">{market.universe === "all" ? "全A股" : market.universe}</span>
        </span>
        <span>
          时间: <span className="text-slate-300">{timeRange.start_date} ~ {timeRange.end_date}</span>
        </span>
        <span>
          频率: <span className="text-slate-300">{{ daily: "日度", weekly: "周度", monthly: "月度", custom: "自定义" }[execution.rebalance_freq]}</span>
        </span>
        <span>
          持仓: <span className="text-slate-300">{execution.holding_count}只</span>
        </span>
        <span>
          成本: <span className="text-slate-300">{((costModel.commission_rate + costModel.stamp_tax + costModel.transfer_fee) * 20000).toFixed(1)} bps双边</span>
        </span>
        {riskAdvanced.walk_forward && (
          <span className="text-blue-400">Walk-Forward 已启用</span>
        )}
        {dynamicPosition.enabled && (
          <span className="text-blue-400">动态仓位 已启用</span>
        )}
      </div>
    </div>
  );
}
