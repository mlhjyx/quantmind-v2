import type { StrategyCreatePayload } from "@/api/strategies";
import type { FactorSummary } from "@/api/factors";

interface StrategyPreviewProps {
  config: StrategyCreatePayload;
  allFactors: FactorSummary[];
}

const WEIGHT_LABELS: Record<string, string> = {
  equal: "等权",
  ic_weighted: "IC加权",
  custom: "自定义",
};

const FREQ_LABELS: Record<string, string> = {
  daily: "日度",
  weekly: "周度",
  monthly: "月度",
};

export function StrategyPreview({ config, allFactors }: StrategyPreviewProps) {
  const selectedFactors = allFactors.filter((f) => config.factor_ids.includes(f.id));

  // Capital constraint check
  const perStockCapital = config.top_n > 0 ? config.initial_capital / config.top_n : 0;
  const maxStockPrice = 200; // 200元 threshold estimate
  const capitalWarning = perStockCapital < maxStockPrice * 100;

  // Avg IC of selected factors
  const avgIC =
    selectedFactors.length > 0
      ? selectedFactors.reduce((sum, f) => sum + Math.abs(f.ic), 0) / selectedFactors.length
      : 0;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-200">配置预览</h3>

      {/* Capital warning */}
      {capitalWarning && config.top_n > 0 && (
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl bg-yellow-500/10 border border-yellow-500/20">
          <span className="text-yellow-400 shrink-0">⚠️</span>
          <p className="text-xs text-yellow-300 leading-relaxed">
            初始资金¥{(config.initial_capital / 10000).toFixed(0)}万 / 持仓{config.top_n}只 = 单只约¥{(perStockCapital / 10000).toFixed(2)}万，部分高价股无法买满1手
          </p>
        </div>
      )}

      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-2">
        <div className="px-3 py-2.5 rounded-xl bg-white/5 border border-white/5">
          <p className="text-xs text-slate-500">持仓数量</p>
          <p className="text-lg font-semibold text-slate-200 mt-0.5">{config.top_n}</p>
        </div>
        <div className="px-3 py-2.5 rounded-xl bg-white/5 border border-white/5">
          <p className="text-xs text-slate-500">调仓频率</p>
          <p className="text-lg font-semibold text-slate-200 mt-0.5">{FREQ_LABELS[config.rebalance_freq] ?? config.rebalance_freq}</p>
        </div>
        <div className="px-3 py-2.5 rounded-xl bg-white/5 border border-white/5">
          <p className="text-xs text-slate-500">权重方式</p>
          <p className="text-base font-semibold text-slate-200 mt-0.5">{WEIGHT_LABELS[config.weight_method] ?? config.weight_method}</p>
        </div>
        <div className="px-3 py-2.5 rounded-xl bg-white/5 border border-white/5">
          <p className="text-xs text-slate-500">行业上限</p>
          <p className="text-lg font-semibold text-slate-200 mt-0.5">{(config.industry_cap * 100).toFixed(0)}%</p>
        </div>
      </div>

      {/* Selected factors summary */}
      <div>
        <p className="text-xs text-slate-500 mb-2">已选因子 ({selectedFactors.length})</p>
        {selectedFactors.length === 0 ? (
          <p className="text-xs text-slate-600 italic">未选择因子</p>
        ) : (
          <div className="space-y-1.5">
            {selectedFactors.map((f) => (
              <div key={f.id} className="flex items-center justify-between">
                <span className="text-xs text-slate-300 truncate flex-1">{f.name}</span>
                <span className="text-xs text-slate-500 ml-2">IC {f.ic.toFixed(3)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Average IC */}
      {selectedFactors.length > 0 && (
        <div className="px-3 py-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20">
          <p className="text-xs text-slate-400">平均 |IC|</p>
          <p className="text-xl font-semibold text-blue-300 mt-0.5">{avgIC.toFixed(4)}</p>
          <p className="text-xs text-slate-500 mt-0.5">
            {avgIC >= 0.05 ? "✅ IC充足" : avgIC >= 0.03 ? "🟡 IC偏低" : "🔴 IC过低，建议检查因子质量"}
          </p>
        </div>
      )}

      {/* Initial capital */}
      <div className="px-3 py-2.5 rounded-xl bg-white/5 border border-white/5">
        <p className="text-xs text-slate-500">初始资金</p>
        <p className="text-base font-semibold text-slate-200 mt-0.5">
          ¥{(config.initial_capital / 10000).toFixed(0)} 万元
        </p>
      </div>
    </div>
  );
}
