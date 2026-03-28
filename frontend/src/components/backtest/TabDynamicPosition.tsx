export interface DynamicPositionConfig {
  enabled: boolean;
  signal_type: "ma_momentum" | "median" | "breadth";
  full_position_threshold: number;
  half_position_threshold: number;
  empty_position_threshold: number;
  signal_smooth_days: number;
}

interface TabDynamicPositionProps {
  value: DynamicPositionConfig;
  onChange: (updates: Partial<DynamicPositionConfig>) => void;
}

const SIGNAL_OPTIONS: { value: DynamicPositionConfig["signal_type"]; label: string; desc: string }[] = [
  { value: "ma_momentum", label: "指数20d均值动量", desc: "沪深300 20日均线相对位置" },
  { value: "median", label: "中位数法", desc: "全市场股票中位数动量信号" },
  { value: "breadth", label: "市场广度", desc: "上涨股票占比信号" },
];

export function TabDynamicPosition({ value, onChange }: TabDynamicPositionProps) {
  return (
    <div className="space-y-6">
      {/* Enable toggle */}
      <div className="flex items-center justify-between p-4 rounded-xl border border-white/10 bg-white/5">
        <div>
          <p className="text-sm font-medium text-slate-200">启用动态仓位</p>
          <p className="text-xs text-slate-500 mt-0.5">根据市场信号动态调整满仓/半仓/空仓</p>
        </div>
        <button
          onClick={() => onChange({ enabled: !value.enabled })}
          className={`relative w-12 h-6 rounded-full transition-colors ${
            value.enabled ? "bg-blue-600" : "bg-slate-600"
          }`}
        >
          <span
            className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${
              value.enabled ? "translate-x-7" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      {value.enabled && (
        <>
          {/* Signal type */}
          <div>
            <label className="text-sm font-medium text-slate-300 block mb-3">仓位信号</label>
            <div className="space-y-2">
              {SIGNAL_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                    value.signal_type === opt.value
                      ? "border-blue-500/60 bg-blue-500/10"
                      : "border-white/10 hover:border-white/20"
                  }`}
                >
                  <input
                    type="radio"
                    name="signal_type"
                    value={opt.value}
                    checked={value.signal_type === opt.value}
                    onChange={() => onChange({ signal_type: opt.value })}
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

          {/* Thresholds */}
          <div>
            <label className="text-sm font-medium text-slate-300 block mb-3">仓位阈值</label>
            <div className="space-y-4">
              {[
                { key: "full_position_threshold", label: "满仓阈值", color: "text-green-400", desc: "信号 > 阈值 → 满仓" },
                { key: "half_position_threshold", label: "半仓阈值", color: "text-yellow-400", desc: "阈值 ≤ 信号 ≤ 满仓阈值 → 半仓" },
                { key: "empty_position_threshold", label: "空仓阈值", color: "text-red-400", desc: "信号 < 阈值 → 空仓" },
              ].map((field) => (
                <div key={field.key} className="flex items-center gap-4">
                  <div className="w-32">
                    <p className={`text-xs font-medium ${field.color}`}>{field.label}</p>
                    <p className="text-xs text-slate-600 mt-0.5">{field.desc}</p>
                  </div>
                  <input
                    type="number"
                    step="0.01"
                    value={value[field.key as keyof DynamicPositionConfig] as number}
                    onChange={(e) => onChange({ [field.key]: Number(e.target.value) })}
                    className="w-28 px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
                  />
                  <div className="h-2 flex-1 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        field.color.includes("green") ? "bg-green-500/40" :
                        field.color.includes("yellow") ? "bg-yellow-500/40" :
                        "bg-red-500/40"
                      }`}
                      style={{ width: `${Math.abs((value[field.key as keyof DynamicPositionConfig] as number) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Signal smooth */}
          <div>
            <label className="text-sm font-medium text-slate-300 block mb-2">
              信号平滑天数: <span className="text-blue-300">{value.signal_smooth_days}</span>
            </label>
            <input
              type="range"
              min={1}
              max={20}
              step={1}
              value={value.signal_smooth_days}
              onChange={(e) => onChange({ signal_smooth_days: Number(e.target.value) })}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-xs text-slate-600 mt-0.5">
              <span>1日 (快)</span><span>20日 (慢)</span>
            </div>
          </div>

          {/* Switching cost estimate */}
          <div className="px-4 py-3 rounded-xl bg-yellow-500/10 border border-yellow-500/20">
            <p className="text-xs font-medium text-yellow-400 mb-1">仓位切换成本预估</p>
            <p className="text-xs text-yellow-300/70">
              每次仓位切换产生额外换手成本。满仓→空仓≈100%换手，建议设置平滑天数 ≥ 5 以减少频繁切换。
            </p>
          </div>
        </>
      )}

      {!value.enabled && (
        <div className="text-center py-8 text-slate-600">
          <p className="text-sm">动态仓位已禁用</p>
          <p className="text-xs mt-1">启用后根据市场信号自动调整仓位水平</p>
        </div>
      )}
    </div>
  );
}
