import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import type { ApprovalItem } from "@/api/pipeline";

interface ApprovalPanelProps {
  items: ApprovalItem[];
  onApprove: (id: string, note?: string) => void;
  onReject: (id: string, note?: string) => void;
  onHold: (id: string, note?: string) => void;
  loading?: boolean;
}

function StatBadge({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="flex flex-col items-center">
      <span className={`text-sm font-semibold tabular-nums ${color}`}>{value}</span>
      <span className="text-[10px] text-slate-500">{label}</span>
    </div>
  );
}

function ApprovalCard({
  item,
  onApprove,
  onReject,
  onHold,
}: {
  item: ApprovalItem;
  onApprove: (id: string, note?: string) => void;
  onReject: (id: string, note?: string) => void;
  onHold: (id: string, note?: string) => void;
}) {
  const [note, setNote] = useState("");
  const [expanded, setExpanded] = useState(false);

  const typeLabel = item.type === "factor" ? "因子" : "策略";
  const typeColor = item.type === "factor" ? "text-purple-300 bg-purple-500/15 border-purple-500/30" : "text-blue-300 bg-blue-500/15 border-blue-500/30";

  return (
    <GlassCard className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${typeColor}`}>{typeLabel}</span>
          <span className="text-sm font-medium text-slate-200 truncate">{item.name}</span>
        </div>
        <span className="text-[10px] text-slate-500 shrink-0">
          {new Date(item.created_at).toLocaleDateString("zh-CN")}
        </span>
      </div>

      {item.description && (
        <p className="text-xs text-slate-400">{item.description}</p>
      )}

      {/* Factor stats */}
      {item.type === "factor" && (
        <div className="flex gap-4">
          {item.ic_mean != null && (
            <StatBadge label="IC均值" value={item.ic_mean.toFixed(3)} color={item.ic_mean > 0.03 ? "text-green-400" : "text-yellow-400"} />
          )}
          {item.t_stat != null && (
            <StatBadge label="t统计量" value={item.t_stat.toFixed(2)} color={item.t_stat > 2.5 ? "text-green-400" : item.t_stat > 2.0 ? "text-yellow-400" : "text-red-400"} />
          )}
          {item.fdr_t_stat != null && (
            <StatBadge label="FDR t值" value={item.fdr_t_stat.toFixed(2)} color={item.fdr_t_stat > 2.0 ? "text-green-400" : "text-yellow-400"} />
          )}
          {item.engine && (
            <StatBadge label="引擎" value={item.engine.toUpperCase()} color="text-slate-300" />
          )}
        </div>
      )}

      {/* Strategy stats */}
      {item.type === "strategy" && (
        <div className="flex gap-4">
          {item.sharpe != null && (
            <StatBadge label="Sharpe" value={item.sharpe.toFixed(2)} color={item.sharpe >= 1.0 ? "text-green-400" : item.sharpe >= 0.72 ? "text-yellow-400" : "text-red-400"} />
          )}
          {item.mdd != null && (
            <StatBadge label="MDD" value={`${(item.mdd * 100).toFixed(1)}%`} color={Math.abs(item.mdd) < 0.35 ? "text-green-400" : "text-red-400"} />
          )}
        </div>
      )}

      {/* Note input toggle */}
      <button
        className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? "收起备注" : "+ 添加备注"}
      </button>

      {expanded && (
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="审批备注（可选）"
          className="w-full text-xs bg-slate-800/60 border border-white/10 rounded-lg px-3 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
        />
      )}

      <div className="flex gap-2">
        <Button
          size="sm"
          className="flex-1 bg-green-600/20 border border-green-500/40 text-green-300 hover:bg-green-600/30"
          onClick={() => onApprove(item.id, note || undefined)}
        >
          批准
        </Button>
        <Button
          size="sm"
          className="flex-1 bg-yellow-600/20 border border-yellow-500/40 text-yellow-300 hover:bg-yellow-600/30"
          onClick={() => onHold(item.id, note || undefined)}
        >
          暂缓
        </Button>
        <Button
          size="sm"
          className="flex-1 bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30"
          onClick={() => onReject(item.id, note || undefined)}
        >
          拒绝
        </Button>
      </div>
    </GlassCard>
  );
}

export function ApprovalPanel({ items, onApprove, onReject, onHold, loading }: ApprovalPanelProps) {
  const pending = items.filter((i) => !i.decision);
  const decided = items.filter((i) => !!i.decision);

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2].map((i) => (
          <div key={i} className="h-32 rounded-2xl bg-slate-800/40 animate-pulse" />
        ))}
      </div>
    );
  }

  if (pending.length === 0) {
    return (
      <GlassCard className="flex flex-col items-center justify-center py-10 text-center">
        <span className="text-3xl mb-2">✅</span>
        <p className="text-sm text-slate-300 font-medium">审批队列已清空</p>
        <p className="text-xs text-slate-500 mt-1">暂无待处理项目</p>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>待审批 <span className="text-white font-semibold">{pending.length}</span> 项</span>
        {decided.length > 0 && <span className="text-slate-500">本次已处理 {decided.length} 项</span>}
      </div>
      {pending.map((item) => (
        <ApprovalCard
          key={item.id}
          item={item}
          onApprove={onApprove}
          onReject={onReject}
          onHold={onHold}
        />
      ))}
    </div>
  );
}
