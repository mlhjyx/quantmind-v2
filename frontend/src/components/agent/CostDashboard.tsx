import { GlassCard } from "@/components/ui/GlassCard";
import type { CostSummary } from "@/api/agent";

const AGENT_LABELS: Record<string, string> = {
  idea:      "因子发现",
  factor:    "Factor Agent",
  eval:      "Eval Agent",
  diagnosis: "诊断优化",
};

const MODEL_LABELS: Record<string, string> = {
  "deepseek-r1": "DeepSeek-R1",
  "deepseek-v3": "DeepSeek-V3.2",
  "qwen3":       "Qwen3",
};

interface CostDashboardProps {
  summary: CostSummary | null;
  loading?: boolean;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function BarRow({ label, cost, maxCost }: { label: string; cost: number; maxCost: number }) {
  const pct = maxCost > 0 ? (cost / maxCost) * 100 : 0;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 text-slate-400 truncate shrink-0">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-slate-700/60 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500/80 to-purple-500/80 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-16 text-right tabular-nums text-slate-300">¥{cost.toFixed(2)}</span>
    </div>
  );
}

export function CostDashboard({ summary, loading }: CostDashboardProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-32 rounded-2xl bg-slate-800/40 animate-pulse" />
        ))}
      </div>
    );
  }

  if (!summary) {
    return (
      <GlassCard className="flex flex-col items-center justify-center py-8 text-center">
        <span className="text-2xl mb-2">💰</span>
        <p className="text-sm text-slate-400">暂无费用数据</p>
      </GlassCard>
    );
  }

  const agentEntries = Object.entries(summary.by_agent) as [string, { cost_cny: number; tokens: number }][];
  const modelEntries = Object.entries(summary.by_model) as [string, { cost_cny: number; tokens: number }][];
  const maxAgentCost = Math.max(...agentEntries.map(([, v]) => v.cost_cny), 0.01);
  const maxModelCost = Math.max(...modelEntries.map(([, v]) => v.cost_cny), 0.01);

  return (
    <div className="space-y-4">
      {/* Top stats */}
      <div className="grid grid-cols-3 gap-3">
        <GlassCard className="text-center">
          <p className="text-xs text-slate-500 mb-1">{summary.month} 总费用</p>
          <p className="text-xl font-semibold text-white tabular-nums">¥{summary.total_cost_cny.toFixed(2)}</p>
        </GlassCard>
        <GlassCard className="text-center">
          <p className="text-xs text-slate-500 mb-1">输入 Tokens</p>
          <p className="text-xl font-semibold text-blue-300 tabular-nums">{formatTokens(summary.total_input_tokens)}</p>
        </GlassCard>
        <GlassCard className="text-center">
          <p className="text-xs text-slate-500 mb-1">输出 Tokens</p>
          <p className="text-xl font-semibold text-purple-300 tabular-nums">{formatTokens(summary.total_output_tokens)}</p>
        </GlassCard>
      </div>

      {/* By agent */}
      <GlassCard>
        <p className="text-xs font-semibold text-slate-400 mb-3">按 Agent 分布</p>
        <div className="space-y-2">
          {agentEntries.map(([key, val]) => (
            <BarRow
              key={key}
              label={AGENT_LABELS[key] ?? key}
              cost={val.cost_cny}
              maxCost={maxAgentCost}
            />
          ))}
        </div>
      </GlassCard>

      {/* By model */}
      <GlassCard>
        <p className="text-xs font-semibold text-slate-400 mb-3">按模型分布</p>
        <div className="space-y-2">
          {modelEntries.map(([key, val]) => (
            <BarRow
              key={key}
              label={MODEL_LABELS[key] ?? key}
              cost={val.cost_cny}
              maxCost={maxModelCost}
            />
          ))}
        </div>
      </GlassCard>
    </div>
  );
}
