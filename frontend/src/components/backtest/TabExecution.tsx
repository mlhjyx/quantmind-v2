export interface ExecutionConfig {
  fill_price: "next_open" | "next_vwap";
  rebalance_freq: "daily" | "weekly" | "monthly" | "custom";
  signal_day: string;
  holding_count: number;
  weight_method: "equal" | "ic_weighted" | "custom";
}

interface TabExecutionProps {
  value: ExecutionConfig;
  onChange: (updates: Partial<ExecutionConfig>) => void;
}

export function TabExecution({ value, onChange }: TabExecutionProps) {
  return (
    <div className="space-y-6">
      {/* Fill price */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">成交价</label>
        <div className="flex gap-3">
          {[
            { value: "next_open", label: "次日开盘价", desc: "T+1日开盘价，流动性好" },
            { value: "next_vwap", label: "次日VWAP", desc: "次日成交量加权均价，更真实" },
          ].map((opt) => (
            <label
              key={opt.value}
              className={`flex-1 flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                value.fill_price === opt.value
                  ? "border-blue-500/60 bg-blue-500/10"
                  : "border-white/10 hover:border-white/20"
              }`}
            >
              <input
                type="radio"
                name="fill_price"
                value={opt.value}
                checked={value.fill_price === opt.value}
                onChange={() => onChange({ fill_price: opt.value as ExecutionConfig["fill_price"] })}
                className="mt-0.5 accent-blue-500"
              />
              <div>
                <div className="text-sm text-slate-200">{opt.label}</div>
                <div className="text-xs text-slate-500 mt-0.5">{opt.desc}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Rebalance frequency */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">调仓频率</label>
        <div className="grid grid-cols-4 gap-2">
          {[
            { value: "daily", label: "日度" },
            { value: "weekly", label: "周度" },
            { value: "monthly", label: "月度" },
            { value: "custom", label: "自定义" },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => onChange({ rebalance_freq: opt.value as ExecutionConfig["rebalance_freq"] })}
              className={`py-2 rounded-xl border text-sm transition-colors ${
                value.rebalance_freq === opt.value
                  ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                  : "border-white/10 text-slate-400 hover:border-white/20"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {value.rebalance_freq === "custom" && (
          <input
            type="text"
            placeholder="Cron表达式 (e.g. 0 9 1 * *)"
            value={value.signal_day}
            onChange={(e) => onChange({ signal_day: e.target.value })}
            className="mt-2 w-full px-3 py-2 text-xs bg-white/5 border border-white/10 rounded-xl text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/50 font-mono"
          />
        )}
      </div>

      {/* Holding count slider */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">
          持仓数量: <span className="text-blue-300 font-semibold">{value.holding_count}</span>
        </label>
        <input
          type="range"
          min={5}
          max={50}
          step={1}
          value={value.holding_count}
          onChange={(e) => onChange({ holding_count: Number(e.target.value) })}
          className="w-full accent-blue-500"
        />
        <div className="flex justify-between text-xs text-slate-600 mt-1">
          <span>5只 (集中)</span>
          <span>50只 (分散)</span>
        </div>
      </div>

      {/* Weight method */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">权重方式</label>
        <div className="flex gap-3">
          {[
            { value: "equal", label: "等权", desc: "每只股票相同权重" },
            { value: "ic_weighted", label: "IC加权", desc: "按因子IC贡献加权" },
            { value: "custom", label: "自定义", desc: "手动指定权重" },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => onChange({ weight_method: opt.value as ExecutionConfig["weight_method"] })}
              className={`flex-1 px-3 py-2 rounded-xl border text-left text-xs transition-colors ${
                value.weight_method === opt.value
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
    </div>
  );
}
