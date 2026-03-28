import { useState } from "react";

export interface CostModelConfig {
  commission_rate: number;
  stamp_tax: number;
  transfer_fee: number;
  slippage_model: "fixed" | "volume_impact" | "none";
  slippage_bps: number;
  volume_impact_coeff: number;
  max_volume_pct: number;
}

interface TabCostModelProps {
  value: CostModelConfig;
  onChange: (updates: Partial<CostModelConfig>) => void;
}

export function TabCostModel({ value, onChange }: TabCostModelProps) {
  const [showVolumeParams, setShowVolumeParams] = useState(false);

  return (
    <div className="space-y-6">
      {/* Fixed costs */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">固定交易成本</label>
        <div className="grid grid-cols-3 gap-4">
          {[
            { key: "commission_rate", label: "佣金", unit: "bps", multiplier: 10000, placeholder: "3" },
            { key: "stamp_tax", label: "印花税", unit: "bps", multiplier: 10000, placeholder: "10" },
            { key: "transfer_fee", label: "过户费", unit: "bps", multiplier: 10000, placeholder: "0.2" },
          ].map((field) => (
            <div key={field.key}>
              <label className="text-xs text-slate-400 block mb-1.5">
                {field.label} ({field.unit})
              </label>
              <input
                type="number"
                step="0.1"
                min="0"
                placeholder={field.placeholder}
                value={(value[field.key as keyof CostModelConfig] as number * field.multiplier).toFixed(1)}
                onChange={(e) =>
                  onChange({ [field.key]: Number(e.target.value) / field.multiplier })
                }
                className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
              />
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-500 mt-2">
          合计: {((value.commission_rate + value.stamp_tax + value.transfer_fee) * 10000).toFixed(1)} bps/单边
        </p>
      </div>

      {/* Slippage model */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">滑点模型</label>
        <div className="flex gap-3">
          {[
            { value: "none", label: "不考虑", desc: "理想情况" },
            { value: "fixed", label: "固定滑点", desc: "按bps固定" },
            { value: "volume_impact", label: "冲击成本", desc: "按成交量比例" },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => onChange({ slippage_model: opt.value as CostModelConfig["slippage_model"] })}
              className={`flex-1 px-3 py-2 rounded-xl border text-left text-xs transition-colors ${
                value.slippage_model === opt.value
                  ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                  : "border-white/10 text-slate-400 hover:border-white/20"
              }`}
            >
              <div className="font-medium">{opt.label}</div>
              <div className="text-slate-500 mt-0.5">{opt.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Fixed slippage input */}
      {value.slippage_model === "fixed" && (
        <div>
          <label className="text-xs text-slate-400 block mb-1.5">固定滑点 (bps)</label>
          <input
            type="number"
            step="1"
            min="0"
            value={(value.slippage_bps).toFixed(0)}
            onChange={(e) => onChange({ slippage_bps: Number(e.target.value) })}
            className="w-48 px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
          />
        </div>
      )}

      {/* Volume impact params */}
      {value.slippage_model === "volume_impact" && (
        <div className="space-y-3">
          <button
            onClick={() => setShowVolumeParams(!showVolumeParams)}
            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            {showVolumeParams ? "▼" : "▶"} Volume-Impact 参数
          </button>
          {showVolumeParams && (
            <div className="grid grid-cols-2 gap-4 pl-4 border-l border-white/10">
              <div>
                <label className="text-xs text-slate-400 block mb-1.5">冲击系数</label>
                <input
                  type="number"
                  step="0.001"
                  value={value.volume_impact_coeff}
                  onChange={(e) => onChange({ volume_impact_coeff: Number(e.target.value) })}
                  className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1.5">成交量上限 (%)</label>
                <input
                  type="number"
                  step="1"
                  min="1"
                  max="30"
                  value={value.max_volume_pct}
                  onChange={(e) => onChange({ max_volume_pct: Number(e.target.value) })}
                  className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Cost summary */}
      <div className="px-4 py-3 rounded-xl bg-white/5 border border-white/5">
        <p className="text-xs font-medium text-slate-400 mb-2">成本摘要</p>
        <div className="space-y-1 text-xs">
          <div className="flex justify-between text-slate-400">
            <span>单边固定成本</span>
            <span className="text-slate-200">{((value.commission_rate + value.stamp_tax + value.transfer_fee) * 10000).toFixed(1)} bps</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>双边总成本</span>
            <span className="text-slate-200">{((value.commission_rate + value.stamp_tax + value.transfer_fee) * 20000).toFixed(1)} bps</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>滑点模型</span>
            <span className="text-slate-200">{value.slippage_model === "none" ? "未启用" : value.slippage_model === "fixed" ? `${value.slippage_bps} bps` : "冲击成本"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
