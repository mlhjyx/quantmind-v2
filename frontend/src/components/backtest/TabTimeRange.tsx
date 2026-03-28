export interface TimeRangeConfig {
  start_date: string;
  end_date: string;
  preset: "1y" | "3y" | "5y" | "all" | "custom";
  exclude_2015: boolean;
  exclude_2020: boolean;
  exclude_custom: string;
  market_regime_analysis: boolean;
  regime_method: "ma" | "drawdown";
}

interface TabTimeRangeProps {
  value: TimeRangeConfig;
  onChange: (updates: Partial<TimeRangeConfig>) => void;
}

const PRESETS: { value: TimeRangeConfig["preset"]; label: string; start: string }[] = [
  { value: "1y", label: "近1年", start: "2025-03-01" },
  { value: "3y", label: "近3年", start: "2023-03-01" },
  { value: "5y", label: "近5年", start: "2021-03-01" },
  { value: "all", label: "全部", start: "2015-01-01" },
  { value: "custom", label: "自定义", start: "" },
];

export function TabTimeRange({ value, onChange }: TabTimeRangeProps) {
  function applyPreset(preset: TimeRangeConfig["preset"], start: string) {
    onChange({ preset, start_date: start, end_date: "2026-03-28" });
  }

  return (
    <div className="space-y-6">
      {/* Preset buttons */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">时间范围</label>
        <div className="flex gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => applyPreset(p.value, p.start)}
              className={`px-4 py-2 rounded-xl border text-sm transition-colors ${
                value.preset === p.value
                  ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                  : "border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-300"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Date range */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1.5">开始日期</label>
          <input
            type="date"
            value={value.start_date}
            onChange={(e) => onChange({ start_date: e.target.value, preset: "custom" })}
            className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1.5">结束日期</label>
          <input
            type="date"
            value={value.end_date}
            onChange={(e) => onChange({ end_date: e.target.value, preset: "custom" })}
            className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
          />
        </div>
      </div>

      {/* Exclude periods */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">排除特殊时期</label>
        <div className="space-y-2">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={value.exclude_2015}
              onChange={(e) => onChange({ exclude_2015: e.target.checked })}
              className="w-4 h-4 accent-blue-500"
            />
            <span className="text-sm text-slate-300">2015年股灾 (2015-06 ~ 2015-09)</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={value.exclude_2020}
              onChange={(e) => onChange({ exclude_2020: e.target.checked })}
              className="w-4 h-4 accent-blue-500"
            />
            <span className="text-sm text-slate-300">2020年疫情 (2020-01 ~ 2020-03)</span>
          </label>
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={!!value.exclude_custom}
              onChange={(e) => !e.target.checked && onChange({ exclude_custom: "" })}
              className="w-4 h-4 accent-blue-500"
            />
            <input
              type="text"
              placeholder="自定义排除: 2022-01-01,2022-06-30"
              value={value.exclude_custom}
              onChange={(e) => onChange({ exclude_custom: e.target.value })}
              className="flex-1 px-3 py-1.5 text-xs bg-white/5 border border-white/10 rounded-lg text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/50"
            />
          </div>
        </div>
      </div>

      {/* Market regime */}
      <div>
        <label className="flex items-center gap-3 cursor-pointer mb-3">
          <input
            type="checkbox"
            checked={value.market_regime_analysis}
            onChange={(e) => onChange({ market_regime_analysis: e.target.checked })}
            className="w-4 h-4 accent-blue-500"
          />
          <span className="text-sm text-slate-300">市场状态分析</span>
        </label>

        {value.market_regime_analysis && (
          <div className="ml-7">
            <label className="text-xs text-slate-400 block mb-2">判定方法</label>
            <div className="flex gap-3">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="regime_method"
                  value="ma"
                  checked={value.regime_method === "ma"}
                  onChange={() => onChange({ regime_method: "ma" })}
                  className="accent-blue-500"
                />
                <span className="text-sm text-slate-300">均线法</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="regime_method"
                  value="drawdown"
                  checked={value.regime_method === "drawdown"}
                  onChange={() => onChange({ regime_method: "drawdown" })}
                  className="accent-blue-500"
                />
                <span className="text-sm text-slate-300">回撤法</span>
              </label>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
