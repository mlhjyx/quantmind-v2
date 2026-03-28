export interface RiskAdvancedConfig {
  industry_cap: number;
  single_stock_cap: number;
  unfilled_handling: "next_day" | "cancel" | "partial";
  walk_forward: boolean;
  wf_train_months: number;
  wf_test_months: number;
  turnover_control: boolean;
  max_turnover: number;
  round_lot_constraint: boolean;
  config_template_name: string;
}

interface TabRiskAdvancedProps {
  value: RiskAdvancedConfig;
  onChange: (updates: Partial<RiskAdvancedConfig>) => void;
  onSaveTemplate: () => void;
  onLoadTemplate: () => void;
  onResetDefault: () => void;
  estimatedDuration?: string;
}

export function TabRiskAdvanced({
  value,
  onChange,
  onSaveTemplate,
  onLoadTemplate,
  onResetDefault,
  estimatedDuration,
}: TabRiskAdvancedProps) {
  return (
    <div className="space-y-6">
      {/* Position limits */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">仓位限制</label>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <label className="text-xs text-slate-400 block mb-2">
              行业上限: <span className="text-slate-200">{(value.industry_cap * 100).toFixed(0)}%</span>
            </label>
            <input
              type="range"
              min={10}
              max={50}
              step={5}
              value={value.industry_cap * 100}
              onChange={(e) => onChange({ industry_cap: Number(e.target.value) / 100 })}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-xs text-slate-600 mt-0.5">
              <span>10%</span><span>50%</span>
            </div>
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-2">
              单股上限: <span className="text-slate-200">{(value.single_stock_cap * 100).toFixed(0)}%</span>
            </label>
            <input
              type="range"
              min={2}
              max={20}
              step={1}
              value={value.single_stock_cap * 100}
              onChange={(e) => onChange({ single_stock_cap: Number(e.target.value) / 100 })}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-xs text-slate-600 mt-0.5">
              <span>2%</span><span>20%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Unfilled handling */}
      <div>
        <label className="text-sm font-medium text-slate-300 block mb-3">未成交处理</label>
        <div className="flex gap-3">
          {[
            { value: "next_day", label: "顺延次日", desc: "继续尝试成交" },
            { value: "cancel", label: "直接取消", desc: "放弃本次调仓" },
            { value: "partial", label: "部分成交", desc: "按实际成交量" },
          ].map((opt) => (
            <label
              key={opt.value}
              className={`flex-1 flex items-start gap-2 p-3 rounded-xl border cursor-pointer transition-colors ${
                value.unfilled_handling === opt.value
                  ? "border-blue-500/60 bg-blue-500/10"
                  : "border-white/10 hover:border-white/20"
              }`}
            >
              <input
                type="radio"
                name="unfilled_handling"
                value={opt.value}
                checked={value.unfilled_handling === opt.value}
                onChange={() => onChange({ unfilled_handling: opt.value as RiskAdvancedConfig["unfilled_handling"] })}
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

      {/* Walk-Forward */}
      <div>
        <label className="flex items-center gap-3 cursor-pointer mb-3">
          <input
            type="checkbox"
            checked={value.walk_forward}
            onChange={(e) => onChange({ walk_forward: e.target.checked })}
            className="w-4 h-4 accent-blue-500"
          />
          <span className="text-sm text-slate-300">Walk-Forward 验证</span>
        </label>
        {value.walk_forward && (
          <div className="grid grid-cols-2 gap-4 ml-7">
            <div>
              <label className="text-xs text-slate-400 block mb-1.5">训练窗口 (月)</label>
              <input
                type="number"
                min={6}
                max={60}
                value={value.wf_train_months}
                onChange={(e) => onChange({ wf_train_months: Number(e.target.value) })}
                className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1.5">测试窗口 (月)</label>
              <input
                type="number"
                min={1}
                max={12}
                value={value.wf_test_months}
                onChange={(e) => onChange({ wf_test_months: Number(e.target.value) })}
                className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 focus:outline-none focus:border-blue-500/50"
              />
            </div>
          </div>
        )}
      </div>

      {/* Turnover control */}
      <div>
        <label className="flex items-center gap-3 cursor-pointer mb-2">
          <input
            type="checkbox"
            checked={value.turnover_control}
            onChange={(e) => onChange({ turnover_control: e.target.checked })}
            className="w-4 h-4 accent-blue-500"
          />
          <span className="text-sm text-slate-300">换手率控制</span>
        </label>
        {value.turnover_control && (
          <div className="ml-7">
            <label className="text-xs text-slate-400 block mb-1.5">
              最大单次换手率: <span className="text-slate-200">{(value.max_turnover * 100).toFixed(0)}%</span>
            </label>
            <input
              type="range"
              min={10}
              max={100}
              step={5}
              value={value.max_turnover * 100}
              onChange={(e) => onChange({ max_turnover: Number(e.target.value) / 100 })}
              className="w-full accent-blue-500"
            />
          </div>
        )}
      </div>

      {/* Round lot constraint */}
      <label className="flex items-center gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={value.round_lot_constraint}
          onChange={(e) => onChange({ round_lot_constraint: e.target.checked })}
          className="w-4 h-4 accent-blue-500"
        />
        <span className="text-sm text-slate-300">整手约束 (A股100股/手)</span>
      </label>

      {/* Template actions + estimated time */}
      <div className="flex items-center justify-between pt-2 border-t border-white/5">
        <div className="flex gap-2">
          <button onClick={onSaveTemplate} className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1.5 rounded-lg border border-white/10 hover:border-white/20 transition-colors">
            保存模板
          </button>
          <button onClick={onLoadTemplate} className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1.5 rounded-lg border border-white/10 hover:border-white/20 transition-colors">
            加载模板
          </button>
          <button onClick={onResetDefault} className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1.5 rounded-lg border border-white/10 hover:border-white/20 transition-colors">
            恢复默认
          </button>
        </div>
        {estimatedDuration && (
          <span className="text-xs text-slate-500">预估耗时: <span className="text-slate-300">{estimatedDuration}</span></span>
        )}
      </div>
    </div>
  );
}
