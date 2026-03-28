import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import type { StrategyCreatePayload } from "@/api/strategies";

interface StrategyEditorProps {
  value: StrategyCreatePayload;
  onChange: (updates: Partial<StrategyCreatePayload>) => void;
  onSave: () => void;
  onRunBacktest: () => void;
  saving?: boolean;
}

type EditMode = "visual" | "code";

const REBALANCE_OPTIONS: { value: StrategyCreatePayload["rebalance_freq"]; label: string }[] = [
  { value: "daily", label: "日度" },
  { value: "weekly", label: "周度" },
  { value: "monthly", label: "月度" },
];

const WEIGHT_OPTIONS: { value: StrategyCreatePayload["weight_method"]; label: string }[] = [
  { value: "equal", label: "等权" },
  { value: "ic_weighted", label: "IC加权" },
  { value: "custom", label: "自定义" },
];

// Visual pipeline nodes
const PIPELINE_NODES = [
  { key: "factor", label: "因子选择", icon: "🧬" },
  { key: "preprocess", label: "预处理", icon: "⚙️" },
  { key: "composite", label: "合成评分", icon: "📊" },
  { key: "filter", label: "过滤", icon: "🔍" },
  { key: "portfolio", label: "持仓构建", icon: "💼" },
];

function VisualMode({ value, onChange }: Pick<StrategyEditorProps, "value" | "onChange">) {
  const [activeNode, setActiveNode] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      {/* Pipeline flowchart */}
      <div>
        <p className="text-xs text-slate-500 mb-3">点击节点配置参数</p>
        <div className="flex items-center gap-2 flex-wrap">
          {PIPELINE_NODES.map((node, i) => (
            <div key={node.key} className="flex items-center gap-2">
              <button
                onClick={() => setActiveNode(activeNode === node.key ? null : node.key)}
                className={`flex flex-col items-center gap-1 px-4 py-3 rounded-xl border transition-all ${
                  activeNode === node.key
                    ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                    : "border-white/10 bg-white/5 text-slate-300 hover:border-white/20"
                }`}
              >
                <span className="text-lg">{node.icon}</span>
                <span className="text-xs whitespace-nowrap">{node.label}</span>
              </button>
              {i < PIPELINE_NODES.length - 1 && (
                <span className="text-slate-600 text-sm">→</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Active node config panel */}
      {activeNode === "factor" && (
        <GlassCard padding="sm">
          <p className="text-xs font-medium text-slate-300 mb-3">因子选择配置</p>
          <p className="text-xs text-slate-500">在左侧面板勾选因子，已选 {value.factor_ids.length} 个</p>
        </GlassCard>
      )}

      {activeNode === "preprocess" && (
        <GlassCard padding="sm">
          <p className="text-xs font-medium text-slate-300 mb-3">预处理参数</p>
          <div className="space-y-2 text-xs text-slate-400">
            <div className="flex items-center justify-between">
              <span>去极值</span>
              <span className="text-slate-200">MAD方法 (3σ)</span>
            </div>
            <div className="flex items-center justify-between">
              <span>标准化</span>
              <span className="text-slate-200">截面z-score</span>
            </div>
            <div className="flex items-center justify-between">
              <span>中性化</span>
              <span className="text-slate-200">市值 + 行业</span>
            </div>
          </div>
        </GlassCard>
      )}

      {activeNode === "composite" && (
        <GlassCard padding="sm">
          <p className="text-xs font-medium text-slate-300 mb-3">合成方式</p>
          <div className="flex gap-2">
            {WEIGHT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => onChange({ weight_method: opt.value })}
                className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                  value.weight_method === opt.value
                    ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                    : "border-white/10 text-slate-400 hover:border-white/20"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </GlassCard>
      )}

      {activeNode === "filter" && (
        <GlassCard padding="sm">
          <p className="text-xs font-medium text-slate-300 mb-3">过滤规则</p>
          <div className="space-y-2 text-xs text-slate-400">
            <div className="flex items-center justify-between">
              <span>剔除ST/退市</span>
              <span className="text-green-400">已启用</span>
            </div>
            <div className="flex items-center justify-between">
              <span>剔除涨跌停</span>
              <span className="text-green-400">已启用</span>
            </div>
            <div className="flex items-center justify-between">
              <span>行业上限</span>
              <span className="text-slate-200">{(value.industry_cap * 100).toFixed(0)}%</span>
            </div>
          </div>
        </GlassCard>
      )}

      {activeNode === "portfolio" && (
        <GlassCard padding="sm">
          <p className="text-xs font-medium text-slate-300 mb-3">持仓构建</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">持仓数量</label>
              <input
                type="number"
                min={5}
                max={50}
                value={value.top_n}
                onChange={(e) => onChange({ top_n: Number(e.target.value) })}
                className="w-full px-2 py-1 text-xs bg-white/5 border border-white/10 rounded-lg text-slate-200 focus:outline-none focus:border-blue-500/50"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">单股上限</label>
              <input
                type="number"
                min={1}
                max={20}
                value={(value.single_stock_cap * 100).toFixed(0)}
                onChange={(e) => onChange({ single_stock_cap: Number(e.target.value) / 100 })}
                className="w-full px-2 py-1 text-xs bg-white/5 border border-white/10 rounded-lg text-slate-200 focus:outline-none focus:border-blue-500/50"
              />
            </div>
          </div>
        </GlassCard>
      )}

      {/* Core parameters */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-slate-400 block mb-2">调仓频率</label>
          <div className="flex gap-2">
            {REBALANCE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => onChange({ rebalance_freq: opt.value })}
                className={`flex-1 py-1.5 rounded-lg text-xs border transition-colors ${
                  value.rebalance_freq === opt.value
                    ? "border-blue-500/60 bg-blue-500/10 text-blue-200"
                    : "border-white/10 text-slate-400 hover:border-white/20"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-2">持仓数量: <span className="text-slate-200">{value.top_n}</span></label>
          <input
            type="range"
            min={5}
            max={50}
            step={1}
            value={value.top_n}
            onChange={(e) => onChange({ top_n: Number(e.target.value) })}
            className="w-full accent-blue-500"
          />
          <div className="flex justify-between text-xs text-slate-600 mt-0.5">
            <span>5</span><span>50</span>
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-2">行业上限: <span className="text-slate-200">{(value.industry_cap * 100).toFixed(0)}%</span></label>
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
          <label className="text-xs text-slate-400 block mb-2">初始资金 (万元)</label>
          <input
            type="number"
            min={10}
            step={10}
            value={value.initial_capital / 10000}
            onChange={(e) => onChange({ initial_capital: Number(e.target.value) * 10000 })}
            className="w-full px-2 py-1.5 text-xs bg-white/5 border border-white/10 rounded-lg text-slate-200 focus:outline-none focus:border-blue-500/50"
          />
        </div>
      </div>
    </div>
  );
}

function CodeMode({ value }: Pick<StrategyEditorProps, "value">) {
  const codePreview = `# QuantMind V2 策略配置
strategy = {
    "name": "${value.name || '未命名策略'}",
    "factors": ${JSON.stringify(value.factor_ids, null, 4)},
    "top_n": ${value.top_n},
    "rebalance_freq": "${value.rebalance_freq}",
    "weight_method": "${value.weight_method}",
    "industry_cap": ${value.industry_cap},
    "single_stock_cap": ${value.single_stock_cap},
    "initial_capital": ${value.initial_capital},
}`;

  return (
    <div className="relative">
      <div className="absolute top-2 right-2">
        <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded">Python</span>
      </div>
      <pre className="bg-[rgba(10,15,35,0.8)] rounded-xl border border-white/10 p-4 text-xs text-slate-300 overflow-auto font-mono leading-relaxed min-h-[200px]">
        {codePreview}
      </pre>
      <p className="text-xs text-slate-500 mt-2">
        Monaco Editor (完整代码模式) — Sprint 1.18 实现
      </p>
    </div>
  );
}

export function StrategyEditor({ value, onChange, onSave, onRunBacktest, saving }: StrategyEditorProps) {
  const [mode, setMode] = useState<EditMode>("visual");

  return (
    <div className="flex flex-col h-full">
      {/* Mode toggle + actions */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-1 bg-white/5 rounded-xl p-1">
          {(["visual", "code"] as EditMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                mode === m ? "bg-blue-600 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {m === "visual" ? "可视化模式" : "代码模式"}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={onSave} loading={saving}>
            保存
          </Button>
          <Button size="sm" onClick={onRunBacktest}>
            ▶ 运行回测
          </Button>
        </div>
      </div>

      {/* Strategy name */}
      <div className="mb-4">
        <input
          type="text"
          placeholder="策略名称..."
          value={value.name}
          onChange={(e) => onChange({ name: e.target.value })}
          className="w-full px-3 py-2 text-sm bg-white/5 border border-white/10 rounded-xl text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/50"
        />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {mode === "visual" ? (
          <VisualMode value={value} onChange={onChange} />
        ) : (
          <CodeMode value={value} />
        )}
      </div>
    </div>
  );
}
