import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import type { LLMConfig } from "@/api/mining";

interface LLMPanelProps {
  onStart: (config: LLMConfig) => void;
  isRunning?: boolean;
  submitting?: boolean;
  availableFactorIds?: { id: string; name: string }[];
}

const MODELS: { value: LLMConfig["model"]; label: string }[] = [
  { value: "deepseek-r1", label: "DeepSeek-R1 (推理)" },
  { value: "deepseek-v3", label: "DeepSeek-V3.2 (生成)" },
  { value: "qwen3", label: "Qwen3 (通用)" },
];

const MODES: { value: LLMConfig["mode"]; label: string; desc: string }[] = [
  { value: "free", label: "自由生成", desc: "基于投资逻辑自由发挥" },
  { value: "directed", label: "定向生成", desc: "限定字段和算子范围" },
  { value: "improve", label: "改进已有", desc: "基于现有因子优化变体" },
];

const DEFAULT_CONFIG: LLMConfig = {
  model: "deepseek-r1",
  mode: "free",
  hypothesis: "",
  n_candidates: 5,
  temperature: 0.7,
};

export function LLMPanel({
  onStart,
  isRunning = false,
  submitting = false,
  availableFactorIds = [],
}: LLMPanelProps) {
  const [config, setConfig] = useState<LLMConfig>(DEFAULT_CONFIG);

  const set = <K extends keyof LLMConfig>(k: K, v: LLMConfig[K]) =>
    setConfig((prev) => ({ ...prev, [k]: v }));

  const canSubmit = config.hypothesis.trim().length >= 10;

  return (
    <GlassCard>
      <h3 className="text-sm font-semibold text-slate-200 mb-4">LLM因子生成</h3>

      {/* Mode selection */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">生成模式</label>
        <div className="flex gap-2">
          {MODES.map((m) => (
            <button
              key={m.value}
              disabled={isRunning}
              onClick={() => set("mode", m.value)}
              className={[
                "flex-1 px-3 py-2 rounded-xl border text-xs transition-all",
                config.mode === m.value
                  ? "bg-blue-600/20 border-blue-500/50 text-blue-300"
                  : "bg-transparent border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-200",
                isRunning ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
              ].join(" ")}
            >
              <div className="font-medium mb-0.5">{m.label}</div>
              <div className="text-[10px] opacity-70">{m.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Model selection */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">模型</label>
        <div className="flex gap-2">
          {MODELS.map((m) => (
            <button
              key={m.value}
              disabled={isRunning}
              onClick={() => set("model", m.value)}
              className={[
                "px-3 py-1.5 rounded-lg border text-xs transition-all",
                config.model === m.value
                  ? "bg-violet-600/20 border-violet-500/50 text-violet-300"
                  : "bg-transparent border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-200",
                isRunning ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
              ].join(" ")}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Improve mode: select base factor */}
      {config.mode === "improve" && availableFactorIds.length > 0 && (
        <div className="mb-4">
          <label className="text-xs text-slate-400 mb-2 block">基础因子</label>
          <select
            value={config.base_factor_id ?? ""}
            disabled={isRunning}
            onChange={(e) => set("base_factor_id", e.target.value || undefined)}
            className="w-full bg-slate-800 border border-white/10 text-slate-200 text-xs rounded-xl px-3 py-2"
          >
            <option value="">选择基础因子...</option>
            {availableFactorIds.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Hypothesis / Investment logic */}
      <div className="mb-4">
        <label className="text-xs text-slate-400 mb-2 block">
          投资逻辑描述
          <span className="ml-2 text-slate-500">（至少10字）</span>
        </label>
        <textarea
          value={config.hypothesis}
          disabled={isRunning}
          onChange={(e) => set("hypothesis", e.target.value)}
          placeholder="描述你的投资假设，例如：高换手率反转效应——过去5日成交量异常放大的股票，短期内往往出现均值回复..."
          rows={4}
          className={[
            "w-full bg-slate-800 border text-slate-200 text-xs rounded-xl px-3 py-2 resize-none",
            "placeholder:text-slate-600 focus:outline-none focus:border-blue-500/50",
            "disabled:opacity-50",
            !canSubmit && config.hypothesis.length > 0
              ? "border-yellow-500/40"
              : "border-white/10",
          ].join(" ")}
        />
        <div className="flex justify-between mt-1">
          <span className="text-[10px] text-slate-500">
            {!canSubmit && config.hypothesis.length > 0 && "描述太短，至少10个字符"}
          </span>
          <span className="text-[10px] text-slate-500">{config.hypothesis.length} 字符</span>
        </div>
      </div>

      {/* n_candidates + temperature */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="text-xs text-slate-400 mb-2 block">候选数量</label>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={1}
              max={20}
              step={1}
              value={config.n_candidates}
              disabled={isRunning}
              onChange={(e) => set("n_candidates", Number(e.target.value))}
              className="flex-1 accent-blue-500 disabled:opacity-40"
            />
            <span className="text-xs font-mono text-slate-200 w-6 text-right">{config.n_candidates}</span>
          </div>
        </div>
        <div>
          <label className="text-xs text-slate-400 mb-2 block">Temperature</label>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={0.1}
              max={1.5}
              step={0.1}
              value={config.temperature}
              disabled={isRunning}
              onChange={(e) => set("temperature", Number(e.target.value))}
              className="flex-1 accent-violet-500 disabled:opacity-40"
            />
            <span className="text-xs font-mono text-slate-200 w-8 text-right">{config.temperature.toFixed(1)}</span>
          </div>
        </div>
      </div>

      <Button
        size="sm"
        loading={submitting}
        disabled={!canSubmit || isRunning}
        onClick={() => onStart(config)}
      >
        {isRunning ? "生成中..." : "开始生成"}
      </Button>

      {isRunning && (
        <div className="flex items-center gap-2 mt-3 text-xs text-slate-400">
          <svg className="animate-spin h-3.5 w-3.5 text-blue-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          LLM正在生成候选因子，请稍候（预计30-90秒）...
        </div>
      )}
    </GlassCard>
  );
}
