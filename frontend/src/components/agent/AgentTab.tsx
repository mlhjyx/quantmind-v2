import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import type { AgentConfig, ModelId } from "@/api/agent";

const MODEL_OPTIONS: { value: ModelId; label: string; desc: string }[] = [
  { value: "deepseek-r1",  label: "DeepSeek-R1",    desc: "深度推理，适合复杂分析" },
  { value: "deepseek-v3",  label: "DeepSeek-V3.2",  desc: "快速生成，适合大批量任务" },
  { value: "qwen3",        label: "Qwen3",           desc: "中文优化，适合本土化场景" },
];

interface AgentTabProps {
  config: AgentConfig;
  onChange: (updated: Partial<AgentConfig>) => void;
}

function SliderField({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-200 tabular-nums font-medium">
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none bg-slate-700 accent-blue-500 cursor-pointer"
      />
      <div className="flex justify-between text-[10px] text-slate-600">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-xs text-slate-400">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? 0.01}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 text-xs bg-slate-800/60 border border-white/10 rounded-lg px-2 py-1.5 text-right text-slate-200 tabular-nums focus:outline-none focus:border-blue-500/50"
      />
    </div>
  );
}

function ToggleField({
  label,
  desc,
  value,
  onChange,
}: {
  label: string;
  desc?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-xs text-slate-300">{label}</p>
        {desc && <p className="text-[10px] text-slate-500">{desc}</p>}
      </div>
      <button
        onClick={() => onChange(!value)}
        className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${
          value ? "bg-blue-600" : "bg-slate-700"
        }`}
      >
        <span
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all duration-200 ${
            value ? "left-5.5 translate-x-0.5" : "left-0.5"
          }`}
          style={{ left: value ? "calc(100% - 18px)" : "2px" }}
        />
      </button>
    </div>
  );
}

export function AgentTab({ config, onChange }: AgentTabProps) {
  const [promptExpanded, setPromptExpanded] = useState(false);

  return (
    <div className="space-y-4">
      {/* Model selection */}
      <GlassCard>
        <p className="text-xs font-semibold text-slate-400 mb-3">模型选择</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {MODEL_OPTIONS.map((opt) => {
            const selected = config.model === opt.value;
            return (
              <button
                key={opt.value}
                onClick={() => onChange({ model: opt.value })}
                className={[
                  "text-left p-3 rounded-xl border transition-all duration-200",
                  selected
                    ? "border-blue-500/60 bg-blue-900/30 shadow-[0_0_12px_rgba(96,165,250,0.2)]"
                    : "border-white/10 bg-slate-800/40 hover:border-white/20",
                ].join(" ")}
              >
                <p className={`text-xs font-semibold ${selected ? "text-blue-300" : "text-slate-300"}`}>
                  {opt.label}
                </p>
                <p className="text-[10px] text-slate-500 mt-0.5">{opt.desc}</p>
              </button>
            );
          })}
        </div>
      </GlassCard>

      {/* Model parameters */}
      <GlassCard>
        <p className="text-xs font-semibold text-slate-400 mb-4">模型参数</p>
        <div className="space-y-5">
          <SliderField
            label="Temperature"
            value={config.temperature}
            min={0}
            max={2}
            step={0.05}
            onChange={(v) => onChange({ temperature: v })}
            format={(v) => v.toFixed(2)}
          />
          <NumberField
            label="Max Tokens"
            value={config.max_tokens}
            min={256}
            max={32768}
            step={256}
            onChange={(v) => onChange({ max_tokens: v })}
          />
          <NumberField
            label="每日最大运行次数"
            value={config.max_daily_runs}
            min={1}
            max={100}
            step={1}
            onChange={(v) => onChange({ max_daily_runs: v })}
          />
        </div>
      </GlassCard>

      {/* Decision thresholds */}
      <GlassCard>
        <p className="text-xs font-semibold text-slate-400 mb-4">决策阈值</p>
        <div className="space-y-3">
          <NumberField
            label="IC均值阈值"
            value={config.ic_threshold}
            min={0}
            max={0.2}
            step={0.001}
            onChange={(v) => onChange({ ic_threshold: v })}
          />
          <NumberField
            label="t统计量阈值"
            value={config.t_stat_threshold}
            min={1.5}
            max={5.0}
            step={0.1}
            onChange={(v) => onChange({ t_stat_threshold: v })}
          />
          <div className="pt-1 space-y-3 border-t border-white/5">
            <ToggleField
              label="自动入库"
              desc="通过Gate的因子自动加入因子库"
              value={config.auto_archive}
              onChange={(v) => onChange({ auto_archive: v })}
            />
            <ToggleField
              label="自动拒绝"
              desc="不通过Gate的因子自动标记拒绝"
              value={config.auto_reject}
              onChange={(v) => onChange({ auto_reject: v })}
            />
          </div>
        </div>
      </GlassCard>

      {/* System prompt preview */}
      <GlassCard>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-slate-400">System Prompt</p>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setPromptExpanded(!promptExpanded)}
          >
            {promptExpanded ? "收起" : "展开预览"}
          </Button>
        </div>
        {promptExpanded ? (
          <textarea
            value={config.system_prompt}
            onChange={(e) => onChange({ system_prompt: e.target.value })}
            rows={8}
            className="w-full text-xs bg-slate-900/60 border border-white/10 rounded-lg px-3 py-2 text-slate-300 font-mono resize-y focus:outline-none focus:border-blue-500/50"
          />
        ) : (
          <p className="text-xs text-slate-500 line-clamp-2 font-mono">
            {config.system_prompt || "（未配置）"}
          </p>
        )}
      </GlassCard>
    </div>
  );
}
