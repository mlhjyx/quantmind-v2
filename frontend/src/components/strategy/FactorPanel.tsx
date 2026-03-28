import { useState, useMemo } from "react";
import type { FactorSummary } from "@/api/factors";
import { groupFactorsByCategory } from "@/api/factors";

interface FactorPanelProps {
  factors: FactorSummary[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

const CATEGORY_ORDER = ["价量", "流动性", "资金流", "基本面", "市值", "行业"];

function directionLabel(d: 1 | -1) {
  return d === 1 ? "正向" : "反向";
}

function statusBadge(status: FactorSummary["status"]) {
  const map: Record<string, string> = {
    active: "text-green-400",
    new: "text-blue-400",
    degraded: "text-yellow-400",
    retired: "text-slate-500",
  };
  const labels: Record<string, string> = {
    active: "✅",
    new: "🆕",
    degraded: "⚠️",
    retired: "❌",
  };
  return <span className={`text-xs ${map[status] ?? "text-slate-400"}`}>{labels[status] ?? status}</span>;
}

export function FactorPanel({ factors, selectedIds, onChange }: FactorPanelProps) {
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!search.trim()) return factors;
    const q = search.toLowerCase();
    return factors.filter(
      (f) => f.name.toLowerCase().includes(q) || f.category.toLowerCase().includes(q)
    );
  }, [factors, search]);

  const grouped = useMemo(() => groupFactorsByCategory(filtered), [filtered]);

  const sortedCategories = useMemo(() => {
    const cats = Object.keys(grouped);
    return cats.sort((a, b) => {
      const ia = CATEGORY_ORDER.indexOf(a);
      const ib = CATEGORY_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
  }, [grouped]);

  function toggleFactor(id: string) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  }

  function toggleCategory(cat: string) {
    setCollapsed((prev) => ({ ...prev, [cat]: !prev[cat] }));
  }

  const hoveredFactor = hoveredId ? factors.find((f) => f.id === hoveredId) : null;

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="mb-3">
        <input
          type="text"
          placeholder="搜索因子..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-3 py-1.5 text-xs bg-white/5 border border-white/10 rounded-lg text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/50"
        />
      </div>

      {/* Factor count */}
      <div className="text-xs text-slate-500 mb-2">
        已选 <span className="text-blue-400 font-medium">{selectedIds.length}</span> / {factors.length} 个因子
      </div>

      {/* Category groups */}
      <div className="flex-1 overflow-y-auto space-y-1 pr-1 scrollbar-thin">
        {sortedCategories.map((cat) => {
          const catFactors = grouped[cat] ?? [];
          const isCollapsed = collapsed[cat];
          const selectedInCat = catFactors.filter((f) => selectedIds.includes(f.id)).length;

          return (
            <div key={cat} className="rounded-lg border border-white/5 overflow-hidden">
              {/* Category header */}
              <button
                className="w-full flex items-center justify-between px-3 py-1.5 bg-white/5 hover:bg-white/8 transition-colors text-left"
                onClick={() => toggleCategory(cat)}
              >
                <span className="text-xs font-medium text-slate-300">{cat}</span>
                <div className="flex items-center gap-2">
                  {selectedInCat > 0 && (
                    <span className="text-xs text-blue-400 bg-blue-500/10 rounded px-1">
                      {selectedInCat}
                    </span>
                  )}
                  <span className="text-slate-500 text-xs">{isCollapsed ? "▶" : "▼"}</span>
                </div>
              </button>

              {/* Factors */}
              {!isCollapsed && (
                <div className="divide-y divide-white/5">
                  {catFactors.map((factor) => {
                    const isSelected = selectedIds.includes(factor.id);
                    return (
                      <div
                        key={factor.id}
                        className={`flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors ${
                          isSelected ? "bg-blue-500/10" : "hover:bg-white/5"
                        }`}
                        onClick={() => toggleFactor(factor.id)}
                        onMouseEnter={() => setHoveredId(factor.id)}
                        onMouseLeave={() => setHoveredId(null)}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleFactor(factor.id)}
                          className="w-3.5 h-3.5 accent-blue-500 cursor-pointer shrink-0"
                          onClick={(e) => e.stopPropagation()}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1">
                            {statusBadge(factor.status)}
                            <span className={`text-xs truncate ${isSelected ? "text-blue-200" : "text-slate-300"}`}>
                              {factor.name}
                            </span>
                          </div>
                          <div className="text-xs text-slate-500 mt-0.5">
                            IC {factor.ic.toFixed(3)} · {directionLabel(factor.direction)}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Hover tooltip */}
      {hoveredFactor && (
        <div className="mt-3 p-3 rounded-xl border border-white/10 bg-[rgba(15,20,45,0.9)] text-xs space-y-1.5">
          <div className="font-medium text-slate-200">{hoveredFactor.name}</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-400">
            <span>IC</span><span className="text-slate-200">{hoveredFactor.ic.toFixed(4)}</span>
            <span>IR</span><span className="text-slate-200">{hoveredFactor.ir.toFixed(4)}</span>
            <span>t值</span><span className="text-slate-200">{hoveredFactor.t_stat.toFixed(2)}</span>
            <span>方向</span><span className="text-slate-200">{directionLabel(hoveredFactor.direction)}</span>
            <span>建议频率</span><span className="text-slate-200">{hoveredFactor.recommended_freq}</span>
          </div>
          {hoveredFactor.description && (
            <p className="text-slate-500 text-xs leading-relaxed">{hoveredFactor.description}</p>
          )}
        </div>
      )}

      {/* Add custom factor */}
      <button className="mt-3 w-full py-1.5 text-xs text-slate-400 border border-dashed border-white/10 rounded-lg hover:border-blue-500/30 hover:text-blue-400 transition-colors">
        + 自定义因子
      </button>
    </div>
  );
}
