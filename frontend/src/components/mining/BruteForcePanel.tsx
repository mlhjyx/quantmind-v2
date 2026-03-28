import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import type { BruteForceConfig } from "@/api/mining";

interface BruteForcePanelProps {
  onStart: (config: BruteForceConfig) => void;
  isRunning?: boolean;
  submitting?: boolean;
  availableTemplates?: string[];
}

const DEFAULT_TEMPLATES = [
  "ts_mean(field, window)",
  "ts_std(field, window)",
  "ts_rank(field, window)",
  "ts_corr(field1, field2, window)",
  "field / ts_mean(field, window) - 1",
];

const AVAILABLE_FIELDS = [
  "close", "open", "high", "low", "volume", "amount",
  "turnover", "vwap", "ret_1d", "ret_5d",
];

const AVAILABLE_FUNCTIONS = [
  "ts_mean", "ts_std", "ts_rank", "ts_sum",
  "ts_min", "ts_max", "ts_corr", "ts_zscore",
  "rank", "log", "abs", "sign",
];

const WINDOW_OPTIONS = [5, 10, 20, 40, 60];

type MultiToggleProps = {
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
  disabled?: boolean;
};

function MultiToggle({ options, selected, onChange, disabled }: MultiToggleProps) {
  const toggle = (v: string) => {
    if (selected.includes(v)) onChange(selected.filter((x) => x !== v));
    else onChange([...selected, v]);
  };
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o}
          disabled={disabled}
          onClick={() => toggle(o)}
          className={[
            "px-2.5 py-1 rounded-lg border text-[11px] font-mono transition-all",
            selected.includes(o)
              ? "bg-emerald-600/20 border-emerald-500/50 text-emerald-300"
              : "bg-transparent border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-200",
            disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
          ].join(" ")}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

function NumberToggle({
  options,
  selected,
  onChange,
  disabled,
}: {
  options: number[];
  selected: number[];
  onChange: (v: number[]) => void;
  disabled?: boolean;
}) {
  const toggle = (v: number) => {
    if (selected.includes(v)) onChange(selected.filter((x) => x !== v));
    else onChange([...selected, v]);
  };
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o}
          disabled={disabled}
          onClick={() => toggle(o)}
          className={[
            "px-3 py-1 rounded-lg border text-[11px] font-mono transition-all",
            selected.includes(o)
              ? "bg-amber-600/20 border-amber-500/50 text-amber-300"
              : "bg-transparent border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-200",
            disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
          ].join(" ")}
        >
          {o}d
        </button>
      ))}
    </div>
  );
}

function estimateCombinations(config: BruteForceConfig): number {
  const { fields, windows, functions } = config;
  // rough estimate: functions × fields × windows
  return Math.min(
    functions.length * fields.length * windows.length,
    config.max_combinations
  );
}

export function BruteForcePanel({
  onStart,
  isRunning = false,
  submitting = false,
  availableTemplates,
}: BruteForcePanelProps) {
  const templates = availableTemplates ?? DEFAULT_TEMPLATES;

  const [config, setConfig] = useState<BruteForceConfig>({
    template: templates[0] ?? "",
    fields: ["close", "volume", "turnover"],
    windows: [5, 20],
    functions: ["ts_mean", "ts_std", "ts_rank"],
    max_combinations: 1000,
  });

  const set = <K extends keyof BruteForceConfig>(k: K, v: BruteForceConfig[K]) =>
    setConfig((prev) => ({ ...prev, [k]: v }));

  const estimated = estimateCombinations(config);
  const canStart = config.fields.length > 0 && config.windows.length > 0 && config.functions.length > 0;

  return (
    <GlassCard>
      <h3 className="text-sm font-semibold text-slate-200 mb-4">暴力枚举配置</h3>

      {/* Template selection */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">枚举模板</label>
        <div className="flex flex-col gap-1.5">
          {templates.map((t) => (
            <button
              key={t}
              disabled={isRunning}
              onClick={() => set("template", t)}
              className={[
                "w-full text-left px-3 py-2 rounded-xl border text-xs font-mono transition-all",
                config.template === t
                  ? "bg-blue-600/20 border-blue-500/50 text-blue-300"
                  : "bg-transparent border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-200",
                isRunning ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
              ].join(" ")}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Fields */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">
          字段范围
          <span className="ml-2 text-slate-500">({config.fields.length} 已选)</span>
        </label>
        <MultiToggle
          options={AVAILABLE_FIELDS}
          selected={config.fields}
          onChange={(v) => set("fields", v)}
          disabled={isRunning}
        />
      </div>

      {/* Windows */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">
          窗口范围
          <span className="ml-2 text-slate-500">({config.windows.length} 已选)</span>
        </label>
        <NumberToggle
          options={WINDOW_OPTIONS}
          selected={config.windows}
          onChange={(v) => set("windows", v)}
          disabled={isRunning}
        />
      </div>

      {/* Functions */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">
          函数范围
          <span className="ml-2 text-slate-500">({config.functions.length} 已选)</span>
        </label>
        <MultiToggle
          options={AVAILABLE_FUNCTIONS}
          selected={config.functions}
          onChange={(v) => set("functions", v)}
          disabled={isRunning}
        />
      </div>

      {/* Max combinations */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">上限组合数</label>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={100}
            max={10000}
            step={100}
            value={config.max_combinations}
            disabled={isRunning}
            onChange={(e) => set("max_combinations", Number(e.target.value))}
            className="flex-1 accent-amber-500 disabled:opacity-40"
          />
          <span className="text-xs font-mono text-slate-200 w-16 text-right">
            {config.max_combinations.toLocaleString()}
          </span>
        </div>
      </div>

      {/* Estimate */}
      <div className="flex items-center justify-between mb-4 px-3 py-2 rounded-xl bg-slate-800/60 border border-white/5">
        <span className="text-xs text-slate-400">预估组合数</span>
        <span className={`text-xs font-mono font-semibold ${estimated > 5000 ? "text-yellow-400" : "text-slate-200"}`}>
          ~{estimated.toLocaleString()}
          {estimated >= config.max_combinations && (
            <span className="ml-1 text-[10px] text-yellow-500">(已截断)</span>
          )}
        </span>
      </div>

      <Button
        size="sm"
        loading={submitting}
        disabled={!canStart || isRunning}
        onClick={() => onStart(config)}
      >
        {isRunning ? "枚举运行中..." : "启动枚举"}
      </Button>

      {!canStart && (
        <p className="text-[10px] text-yellow-400 mt-2">请至少选择一个字段、窗口和函数</p>
      )}
    </GlassCard>
  );
}
