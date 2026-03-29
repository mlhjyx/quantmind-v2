import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { FactorSummary } from "@/api/factors";

interface Props {
  factors: FactorSummary[];
  onSelect?: (factor: FactorSummary) => void;
}

type SortKey = "name" | "ic" | "ir" | "t_stat" | "fdr_t_stat" | "gate_score";
type SortDir = "asc" | "desc";

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  active:   { label: "✅ 活跃",  cls: "bg-green-500/15 text-green-400 border-green-500/30" },
  new:      { label: "🆕 新入库", cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  degraded: { label: "⚠️ 衰退",  cls: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
  retired:  { label: "❌ 淘汰",  cls: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const STATUS_FILTER_OPTIONS = ["全部", "active", "new", "degraded", "retired"];

function fmtNum(v: number | null | undefined, decimals = 3) {
  return v == null ? "—" : v.toFixed(decimals);
}

export default function FactorTable({ factors, onSelect }: Props) {
  const navigate = useNavigate();
  const [sortKey, setSortKey] = useState<SortKey>("gate_score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [statusFilter, setStatusFilter] = useState("全部");
  const [search, setSearch] = useState("");

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const filtered = factors
    .filter((f) => {
      if (statusFilter !== "全部" && f.status !== statusFilter) return false;
      if (search && !f.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    })
    .sort((a, b) => {
      const av = (a[sortKey] ?? 0) as number;
      const bv = (b[sortKey] ?? 0) as number;
      return sortDir === "asc" ? av - bv : bv - av;
    });

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <span className="text-slate-600 ml-0.5">↕</span>;
    return <span className="text-blue-400 ml-0.5">{sortDir === "asc" ? "↑" : "↓"}</span>;
  }

  function ThBtn({ col, label }: { col: SortKey; label: string }) {
    return (
      <th
        className="px-3 py-2 text-left text-xs font-medium text-slate-400 cursor-pointer hover:text-slate-200 select-none whitespace-nowrap"
        onClick={() => handleSort(col)}
      >
        {label}
        <SortIcon col={col} />
      </th>
    );
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-3">
        <input
          type="text"
          placeholder="搜索因子名..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-48"
        />
        <div className="flex gap-1">
          {STATUS_FILTER_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                statusFilter === s
                  ? "bg-blue-500/20 text-blue-400 border-blue-500/40"
                  : "bg-transparent text-slate-400 border-slate-700 hover:border-slate-500"
              }`}
            >
              {s === "全部" ? "全部" : STATUS_BADGE[s]?.label ?? s}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-slate-500">{filtered.length} 个因子</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full text-sm">
          <thead className="bg-slate-800/60">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-8">#</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">状态</th>
              <ThBtn col="name" label="因子名" />
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">类别</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">策略类型</th>
              <ThBtn col="ic" label="IC均值" />
              <ThBtn col="ir" label="IC_IR" />
              <ThBtn col="t_stat" label="t值" />
              <ThBtn col="fdr_t_stat" label="FDR t值" />
              <ThBtn col="gate_score" label="Gate得分" />
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">来源</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={12} className="text-center py-10 text-slate-500 text-xs">
                  暂无数据
                </td>
              </tr>
            ) : (
              filtered.map((f, i) => {
                const badge = STATUS_BADGE[f.status] ?? { label: f.status, cls: "bg-slate-500/15 text-slate-400 border-slate-500/30" };
                const tOk = f.t_stat >= 2.5;
                const fdrOk = f.fdr_t_stat >= 2.0;
                return (
                  <tr
                    key={f.id}
                    className="hover:bg-white/3 transition-colors cursor-pointer"
                    onClick={() => onSelect?.(f)}
                  >
                    <td className="px-3 py-2.5 text-xs text-slate-500">{i + 1}</td>
                    <td className="px-3 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-xs border ${badge.cls}`}>
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-xs font-medium">
                      <span className="font-mono text-slate-200">{f.name}</span>
                      {Math.abs(f.ic) >= 0.02 && (
                        <span
                          className="ml-1.5 text-xs"
                          style={{ color: f.ic > 0.02 ? "#00e5a0" : "#ffb020" }}
                        >
                          {f.ic > 0.02 ? "↑正向" : "↓反向"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-slate-400">{f.category}</td>
                    <td className="px-3 py-2.5 text-xs text-slate-400">{f.strategy_type ?? "—"}</td>
                    <td className="px-3 py-2.5 text-xs tabular-nums">
                      <span style={{
                        color: Math.abs(f.ic) < 0.02 ? "#3d4270" : f.ic > 0.02 ? "#00e5a0" : "#ffb020",
                        fontFamily: "inherit",
                      }}>
                        {fmtNum(f.ic)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-xs tabular-nums">
                      <span className={f.ir >= 0.5 ? "text-green-400" : "text-yellow-400"}>
                        {fmtNum(f.ir, 2)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-xs tabular-nums">
                      <span className={tOk ? "text-slate-200" : "text-yellow-400"}>
                        {fmtNum(f.t_stat, 2)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-xs tabular-nums">
                      <span className={fdrOk ? "text-slate-200" : "text-yellow-400"}>
                        {fmtNum(f.fdr_t_stat, 2)}
                        {!fdrOk && " ⚠️"}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-xs tabular-nums">
                      <div className="flex items-center gap-1.5">
                        <div className="h-1.5 w-16 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 rounded-full"
                            style={{ width: `${f.gate_score ?? 0}%` }}
                          />
                        </div>
                        <span className="text-slate-300">{f.gate_score ?? "—"}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-slate-400">{f.source ?? "—"}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex gap-1">
                        <button
                          className="px-2 py-0.5 text-xs rounded bg-blue-500/15 text-blue-400 border border-blue-500/30 hover:bg-blue-500/25 transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/factors/evaluate/${f.id}`);
                          }}
                        >
                          详情
                        </button>
                        <button
                          className="px-2 py-0.5 text-xs rounded bg-slate-700 text-slate-400 border border-slate-600 hover:bg-slate-600 transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/factors/compare/${f.id}`);
                          }}
                        >
                          对比
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
