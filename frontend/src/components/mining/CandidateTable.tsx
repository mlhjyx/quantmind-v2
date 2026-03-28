import { useState } from "react";
import type { CandidateFactor } from "@/api/mining";
import { Button } from "@/components/ui/Button";

interface CandidateTableProps {
  candidates: CandidateFactor[];
  onSubmitGate: (ids: string[]) => void;
  submitting?: boolean;
}

const GATE_BADGE: Record<string, { label: string; cls: string }> = {
  pending: { label: "待验证", cls: "bg-slate-700 text-slate-300" },
  passed: { label: "通过", cls: "bg-green-900/60 text-green-400 border border-green-500/30" },
  failed: { label: "未通过", cls: "bg-red-900/60 text-red-400 border border-red-500/30" },
};

function tStatColor(t: number) {
  if (t >= 2.5) return "text-green-400";
  if (t >= 2.0) return "text-yellow-400";
  return "text-red-400";
}

export function CandidateTable({ candidates, onSubmitGate, submitting = false }: CandidateTableProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () => {
    if (selected.size === candidates.length) setSelected(new Set());
    else setSelected(new Set(candidates.map((c) => c.id)));
  };

  const pendingSelected = candidates
    .filter((c) => selected.has(c.id) && c.gate_status === "pending")
    .map((c) => c.id);

  if (candidates.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-slate-500">
        <span className="text-3xl mb-2">🧬</span>
        <p className="text-sm">暂无候选因子</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-slate-400">
          共 <span className="text-slate-200 font-medium">{candidates.length}</span> 个候选
          {selected.size > 0 && (
            <span className="ml-2 text-blue-400">已选 {selected.size}</span>
          )}
        </span>
        <div className="flex gap-2">
          {pendingSelected.length > 0 && (
            <Button
              size="sm"
              loading={submitting}
              onClick={() => onSubmitGate(pendingSelected)}
            >
              提交Gate验证 ({pendingSelected.length})
            </Button>
          )}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/10 text-slate-400">
              <th className="pb-2 pr-3 text-left w-8">
                <input
                  type="checkbox"
                  checked={selected.size === candidates.length && candidates.length > 0}
                  onChange={toggleAll}
                  className="accent-blue-500"
                />
              </th>
              <th className="pb-2 pr-4 text-left">名称/表达式</th>
              <th className="pb-2 pr-3 text-right">IC均值</th>
              <th className="pb-2 pr-3 text-right">t值</th>
              <th className="pb-2 pr-3 text-right">FDR t</th>
              <th className="pb-2 pr-3 text-right">IC_IR</th>
              <th className="pb-2 pr-3 text-right">覆盖率</th>
              <th className="pb-2 text-center">Gate</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => {
              const badge = GATE_BADGE[c.gate_status] ?? GATE_BADGE["pending"]!;
              return (
                <tr
                  key={c.id}
                  className="border-b border-white/5 hover:bg-white/[0.03] transition-colors"
                >
                  <td className="py-2 pr-3">
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggle(c.id)}
                      className="accent-blue-500"
                    />
                  </td>
                  <td className="py-2 pr-4 max-w-[220px]">
                    <p className="text-slate-200 font-medium truncate">{c.name}</p>
                    <p className="text-slate-500 font-mono truncate text-[10px] mt-0.5">{c.expression}</p>
                  </td>
                  <td className={`py-2 pr-3 text-right font-mono ${c.ic_mean >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {c.ic_mean.toFixed(4)}
                  </td>
                  <td className={`py-2 pr-3 text-right font-mono ${tStatColor(c.t_stat)}`}>
                    {c.t_stat.toFixed(2)}
                  </td>
                  <td className={`py-2 pr-3 text-right font-mono ${tStatColor(c.fdr_t_stat)}`}>
                    {c.fdr_t_stat.toFixed(2)}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-slate-300">
                    {c.ic_ir.toFixed(3)}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-400">
                    {(c.coverage * 100).toFixed(1)}%
                  </td>
                  <td className="py-2 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${badge.cls}`}>
                      {badge.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
