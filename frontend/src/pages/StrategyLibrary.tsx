import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { listStrategies, type Strategy } from "@/api/strategies";
import { listBacktestHistory, type BacktestHistoryItem } from "@/api/backtest";
import { STALE } from "@/api/QueryProvider";

// ---- Helpers ----

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toFixed(digits);
}

function sharpeColor(v: number | null | undefined): string {
  if (v == null) return "text-slate-400";
  if (v >= 1.0) return "text-green-400";
  if (v >= 0.5) return "text-yellow-400";
  return "text-red-400";
}

function mddColor(v: number | null | undefined): string {
  if (v == null) return "text-slate-400";
  if (v >= -0.15) return "text-green-400";
  if (v >= -0.35) return "text-yellow-400";
  return "text-red-400";
}

function statusBadge(status: BacktestHistoryItem["status"]): { label: string; cls: string } {
  const map: Record<string, { label: string; cls: string }> = {
    completed: { label: "完成", cls: "bg-green-500/20 text-green-400 border-green-500/30" },
    running:   { label: "运行中", cls: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
    failed:    { label: "失败", cls: "bg-red-500/20 text-red-400 border-red-500/30" },
    waiting:   { label: "等待", cls: "bg-slate-500/20 text-slate-400 border-slate-500/30" },
    cancelled: { label: "已取消", cls: "bg-slate-600/20 text-slate-500 border-slate-600/30" },
  };
  return map[status] ?? { label: status, cls: "bg-slate-700/30 text-slate-400 border-slate-600/30" };
}

// ---- Strategy Card ----

interface StrategyCardProps {
  strategy: Strategy;
  selected: boolean;
  compareMode: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onRunBacktest: () => void;
}

function StrategyCard({ strategy, selected, compareMode, onSelect, onEdit, onRunBacktest }: StrategyCardProps) {
  return (
    <GlassCard
      variant={selected ? "selected" : "clickable"}
      onClick={compareMode ? onSelect : undefined}
      className="relative"
    >
      {compareMode && (
        <div className={`absolute top-3 right-3 w-4 h-4 rounded border-2 flex items-center justify-center ${
          selected ? "bg-blue-500 border-blue-500" : "border-slate-500"
        }`}>
          {selected && <span className="text-white text-[10px]">✓</span>}
        </div>
      )}

      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0 pr-8">
          <h3 className="font-semibold text-white truncate">{strategy.name}</h3>
          {strategy.description && (
            <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">{strategy.description}</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3">
        <div>
          <p className="text-[10px] text-slate-400">Sharpe</p>
          <p className={`text-sm font-bold ${sharpeColor(strategy.sharpe)}`}>{fmtNum(strategy.sharpe, 3)}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-400">MDD</p>
          <p className={`text-sm font-bold ${mddColor(strategy.mdd)}`}>{fmtPct(strategy.mdd)}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-400">持仓</p>
          <p className="text-sm font-bold text-white">{strategy.top_n}</p>
        </div>
      </div>

      <div className="flex items-center gap-2 text-[10px] text-slate-500 mb-3 flex-wrap">
        <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{strategy.rebalance_freq === "daily" ? "日频" : strategy.rebalance_freq === "weekly" ? "周频" : "月频"}</span>
        <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{strategy.weight_method === "equal" ? "等权" : strategy.weight_method === "ic_weighted" ? "IC加权" : "自定义"}</span>
        <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{strategy.factor_ids.length}个因子</span>
      </div>

      {!compareMode && (
        <div className="flex gap-1.5">
          <Button variant="ghost" size="sm" className="flex-1 text-xs" onClick={onEdit}>编辑</Button>
          <Button variant="primary" size="sm" className="flex-1 text-xs" onClick={onRunBacktest}>运行回测</Button>
        </div>
      )}
    </GlassCard>
  );
}

// ---- Strategy Row (table view) ----

interface StrategyRowProps {
  strategy: Strategy;
  selected: boolean;
  compareMode: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onRunBacktest: () => void;
}

function StrategyRow({ strategy, selected, compareMode, onSelect, onEdit, onRunBacktest }: StrategyRowProps) {
  return (
    <tr
      className={`border-b border-slate-700/30 hover:bg-white/5 transition-colors ${
        selected ? "bg-blue-500/10" : ""
      }`}
    >
      {compareMode && (
        <td className="py-2 px-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={onSelect}
            className="w-3.5 h-3.5 rounded accent-blue-500"
          />
        </td>
      )}
      <td className="py-2 px-3 font-medium text-white">{strategy.name}</td>
      <td className={`py-2 px-3 font-medium ${sharpeColor(strategy.sharpe)}`}>{fmtNum(strategy.sharpe, 3)}</td>
      <td className={`py-2 px-3 font-medium ${mddColor(strategy.mdd)}`}>{fmtPct(strategy.mdd)}</td>
      <td className="py-2 px-3 text-slate-300">{strategy.top_n}</td>
      <td className="py-2 px-3 text-slate-300">{strategy.factor_ids.length}</td>
      <td className="py-2 px-3 text-slate-400 text-xs">{strategy.rebalance_freq === "daily" ? "日" : strategy.rebalance_freq === "weekly" ? "周" : "月"}</td>
      <td className="py-2 px-3 text-slate-400 text-xs">{strategy.created_at?.slice(0, 10)}</td>
      <td className="py-2 px-3">
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={onEdit}>编辑</Button>
          <Button variant="primary" size="sm" onClick={onRunBacktest}>回测</Button>
        </div>
      </td>
    </tr>
  );
}

// ---- Compare Panel ----

interface ComparePanelProps {
  strategies: Strategy[];
}

function ComparePanel({ strategies }: ComparePanelProps) {
  if (strategies.length < 2) {
    return (
      <GlassCard className="text-center py-10 text-slate-400 text-sm">
        请勾选 2 个策略进行对比
      </GlassCard>
    );
  }

  const a = strategies[0]!;
  const b = strategies[1]!;

  const rows: Array<{ label: string; keyA: string | number | null; keyB: string | number | null; format?: (v: unknown) => string }> = [
    { label: "Sharpe", keyA: a.sharpe ?? null, keyB: b.sharpe ?? null, format: (v) => fmtNum(v as number | null, 3) },
    { label: "MDD", keyA: a.mdd ?? null, keyB: b.mdd ?? null, format: (v) => fmtPct(v as number | null) },
    { label: "持仓数", keyA: a.top_n, keyB: b.top_n, format: String },
    { label: "因子数", keyA: a.factor_ids.length, keyB: b.factor_ids.length, format: String },
    { label: "调仓频率", keyA: a.rebalance_freq, keyB: b.rebalance_freq, format: (v) => v === "daily" ? "日频" : v === "weekly" ? "周频" : "月频" },
    { label: "权重方式", keyA: a.weight_method, keyB: b.weight_method, format: (v) => v === "equal" ? "等权" : v === "ic_weighted" ? "IC加权" : "自定义" },
    { label: "行业上限", keyA: a.industry_cap, keyB: b.industry_cap, format: (v) => fmtPct(v as number) },
    { label: "单股上限", keyA: a.single_stock_cap, keyB: b.single_stock_cap, format: (v) => fmtPct(v as number) },
  ];

  return (
    <GlassCard>
      <div className="grid grid-cols-3 gap-4 mb-4">
        <div />
        <div className="text-center">
          <h3 className="font-semibold text-white truncate">{a?.name}</h3>
        </div>
        <div className="text-center">
          <h3 className="font-semibold text-white truncate">{b?.name}</h3>
        </div>
      </div>
      <div className="space-y-1">
        {rows.map((row, i) => {
          const fmt = row.format ?? String;
          const aVal = fmt(row.keyA);
          const bVal = fmt(row.keyB);
          const aNum = typeof row.keyA === "number" ? row.keyA : null;
          const bNum = typeof row.keyB === "number" ? row.keyB : null;
          const aBetter = aNum != null && bNum != null && aNum > bNum;
          const bBetter = aNum != null && bNum != null && bNum > aNum;
          return (
            <div key={i} className={`grid grid-cols-3 gap-4 py-1.5 px-2 rounded-lg ${i % 2 === 0 ? "bg-white/[0.02]" : ""}`}>
              <span className="text-xs text-slate-400 flex items-center">{row.label}</span>
              <span className={`text-sm font-medium text-center ${aBetter ? "text-green-400" : "text-slate-300"}`}>{aVal}</span>
              <span className={`text-sm font-medium text-center ${bBetter ? "text-green-400" : "text-slate-300"}`}>{bVal}</span>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}

// ---- Backtest History Tab ----

function BacktestHistoryPanel() {
  const navigate = useNavigate();
  const { data: history, isLoading } = useQuery({
    queryKey: ["backtest-history"],
    queryFn: () => listBacktestHistory(),
    staleTime: STALE.factor,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-400 text-sm">
        <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mr-2" />
        加载中...
      </div>
    );
  }

  if (!history || history.length === 0) {
    return <div className="text-center py-12 text-slate-500 text-sm">暂无回测历史</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs text-slate-300">
        <thead>
          <tr className="border-b border-slate-700/60">
            <th className="py-2 px-3 text-left text-slate-400 font-medium">策略名称</th>
            <th className="py-2 px-3 text-left text-slate-400 font-medium">状态</th>
            <th className="py-2 px-3 text-right text-slate-400 font-medium">Sharpe</th>
            <th className="py-2 px-3 text-right text-slate-400 font-medium">MDD</th>
            <th className="py-2 px-3 text-right text-slate-400 font-medium">年化</th>
            <th className="py-2 px-3 text-left text-slate-400 font-medium">创建时间</th>
            <th className="py-2 px-3 text-left text-slate-400 font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {history.map((item) => {
            const badge = statusBadge(item.status);
            return (
              <tr key={item.run_id} className="border-b border-slate-700/30 hover:bg-white/5 transition-colors">
                <td className="py-1.5 px-3 font-medium text-white">{item.strategy_name}</td>
                <td className="py-1.5 px-3">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-medium ${badge.cls}`}>
                    {badge.label}
                  </span>
                </td>
                <td className={`py-1.5 px-3 text-right font-medium ${sharpeColor(item.sharpe)}`}>{fmtNum(item.sharpe, 3)}</td>
                <td className={`py-1.5 px-3 text-right font-medium ${mddColor(item.mdd)}`}>{fmtPct(item.mdd)}</td>
                <td className="py-1.5 px-3 text-right">{fmtPct(item.annual_return)}</td>
                <td className="py-1.5 px-3 text-slate-400">{item.created_at?.slice(0, 16)}</td>
                <td className="py-1.5 px-3">
                  {item.status === "completed" && (
                    <Button variant="ghost" size="sm" onClick={() => navigate(`/backtest/${item.run_id}/result`)}>
                      查看结果
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- Main Page ----

type ViewMode = "card" | "table";
type SortField = "name" | "sharpe" | "mdd" | "created_at";

export default function StrategyLibrary() {
  const navigate = useNavigate();
  const [viewMode, setViewMode] = useState<ViewMode>("card");
  const [compareMode, setCompareMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<"strategies" | "history">("strategies");
  const [searchText, setSearchText] = useState("");
  // filterMarket reserved for future market filter (A股/外汇)
  const [_filterMarket] = useState<string>("all");
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [sortAsc, setSortAsc] = useState(false);
  const [sharpeMin, setSharpeMin] = useState("");
  const [mddMax, setMddMax] = useState("");

  const { data: strategies, isLoading } = useQuery({
    queryKey: ["strategies"],
    queryFn: listStrategies,
    staleTime: STALE.config,
  });

  const filtered = useMemo(() => {
    if (!strategies) return [];
    return strategies
      .filter((s) => {
        if (searchText && !s.name.toLowerCase().includes(searchText.toLowerCase())) return false;
        if (sharpeMin && (s.sharpe == null || s.sharpe < parseFloat(sharpeMin))) return false;
        if (mddMax && (s.mdd == null || Math.abs(s.mdd) > Math.abs(parseFloat(mddMax) / 100))) return false;
        return true;
      })
      .sort((a, b) => {
        let av: string | number, bv: string | number;
        if (sortField === "name") { av = a.name; bv = b.name; }
        else if (sortField === "sharpe") { av = a.sharpe ?? -Infinity; bv = b.sharpe ?? -Infinity; }
        else if (sortField === "mdd") { av = a.mdd ?? -Infinity; bv = b.mdd ?? -Infinity; }
        else { av = a.created_at; bv = b.created_at; }
        if (av < bv) return sortAsc ? -1 : 1;
        if (av > bv) return sortAsc ? 1 : -1;
        return 0;
      });
  }, [strategies, searchText, sharpeMin, mddMax, sortField, sortAsc]);

  const selectedStrategies = useMemo(
    () => (strategies ?? []).filter((s) => selectedIds.includes(s.id)),
    [strategies, selectedIds],
  );

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1] as string, id]; // max 2
      return [...prev, id];
    });
  };

  const handleNewStrategy = () => navigate("/strategy/new");
  const handleEdit = (id: string) => navigate(`/strategy/${id}`);
  const handleRunBacktest = (id: string) => navigate(`/backtest/config?strategy_id=${id}`);

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: "策略库" },
        ]}
      />

      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">策略库</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {strategies ? `${strategies.length} 个策略` : "加载中..."}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={compareMode ? "primary" : "outline"}
            size="sm"
            onClick={() => {
              setCompareMode(!compareMode);
              setSelectedIds([]);
            }}
          >
            {compareMode ? "退出对比" : "对比模式"}
          </Button>
          <Button size="sm" onClick={handleNewStrategy}>+ 新建策略</Button>
        </div>
      </div>

      {/* Tabs: Strategies / History */}
      <div className="flex gap-1 border-b border-slate-700/60 mb-4">
        {(["strategies", "history"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === tab
                ? "text-white border-blue-500"
                : "text-slate-400 border-transparent hover:text-slate-200"
            }`}
          >
            {tab === "strategies" ? "策略列表" : "回测历史"}
          </button>
        ))}
      </div>

      {activeTab === "history" && (
        <GlassCard>
          <BacktestHistoryPanel />
        </GlassCard>
      )}

      {activeTab === "strategies" && (
        <>
          {/* Filters */}
          <GlassCard className="mb-4">
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="text"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder="搜索策略名称..."
                className="bg-slate-700/50 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 w-48"
              />
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-400">Sharpe ≥</span>
                <input
                  type="number"
                  value={sharpeMin}
                  onChange={(e) => setSharpeMin(e.target.value)}
                  placeholder="0.5"
                  className="bg-slate-700/50 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-white w-16 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-400">MDD ≥ -</span>
                <input
                  type="number"
                  value={mddMax}
                  onChange={(e) => setMddMax(e.target.value)}
                  placeholder="35"
                  className="bg-slate-700/50 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-white w-16 focus:outline-none focus:border-blue-500"
                />
                <span className="text-xs text-slate-400">%</span>
              </div>

              {/* Sort */}
              <div className="flex items-center gap-1.5 ml-auto">
                <span className="text-xs text-slate-400">排序:</span>
                <select
                  value={sortField}
                  onChange={(e) => setSortField(e.target.value as SortField)}
                  className="bg-slate-700/50 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="created_at">创建时间</option>
                  <option value="sharpe">Sharpe</option>
                  <option value="mdd">MDD</option>
                  <option value="name">名称</option>
                </select>
                <button
                  onClick={() => setSortAsc(!sortAsc)}
                  className="bg-slate-700/50 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-white hover:bg-slate-600/50"
                >
                  {sortAsc ? "↑ 升序" : "↓ 降序"}
                </button>
              </div>

              {/* View toggle */}
              <div className="flex rounded-lg overflow-hidden border border-slate-600">
                {(["card", "table"] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-3 py-1.5 text-xs transition-colors ${
                      viewMode === mode
                        ? "bg-blue-600 text-white"
                        : "bg-slate-700/50 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {mode === "card" ? "卡片" : "表格"}
                  </button>
                ))}
              </div>
            </div>
          </GlassCard>

          {/* Compare panel */}
          {compareMode && (
            <div className="mb-4">
              <ComparePanel strategies={selectedStrategies} />
            </div>
          )}

          {/* Loading */}
          {isLoading && (
            <GlassCard className="flex items-center justify-center py-16">
              <div className="flex items-center gap-3 text-slate-400">
                <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                <span>加载策略列表...</span>
              </div>
            </GlassCard>
          )}

          {/* Empty */}
          {!isLoading && filtered.length === 0 && (
            <GlassCard className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-slate-400 text-sm mb-3">
                {strategies?.length === 0 ? "暂无策略，点击「新建策略」开始" : "没有符合筛选条件的策略"}
              </p>
              {strategies?.length === 0 && (
                <Button size="sm" onClick={handleNewStrategy}>+ 新建策略</Button>
              )}
            </GlassCard>
          )}

          {/* Card view */}
          {!isLoading && filtered.length > 0 && viewMode === "card" && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {filtered.map((s) => (
                <StrategyCard
                  key={s.id}
                  strategy={s}
                  selected={selectedIds.includes(s.id)}
                  compareMode={compareMode}
                  onSelect={() => toggleSelect(s.id)}
                  onEdit={() => handleEdit(s.id)}
                  onRunBacktest={() => handleRunBacktest(s.id)}
                />
              ))}
            </div>
          )}

          {/* Table view */}
          {!isLoading && filtered.length > 0 && viewMode === "table" && (
            <GlassCard>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-slate-300">
                  <thead>
                    <tr className="border-b border-slate-700/60">
                      {compareMode && <th className="py-2 px-3 w-8" />}
                      <th className="py-2 px-3 text-left text-slate-400 font-medium cursor-pointer hover:text-slate-200" onClick={() => { if (sortField === "name") setSortAsc(!sortAsc); else setSortField("name"); }}>
                        策略名称{sortField === "name" && (sortAsc ? " ↑" : " ↓")}
                      </th>
                      <th className="py-2 px-3 text-right text-slate-400 font-medium cursor-pointer hover:text-slate-200" onClick={() => { if (sortField === "sharpe") setSortAsc(!sortAsc); else setSortField("sharpe"); }}>
                        Sharpe{sortField === "sharpe" && (sortAsc ? " ↑" : " ↓")}
                      </th>
                      <th className="py-2 px-3 text-right text-slate-400 font-medium cursor-pointer hover:text-slate-200" onClick={() => { if (sortField === "mdd") setSortAsc(!sortAsc); else setSortField("mdd"); }}>
                        MDD{sortField === "mdd" && (sortAsc ? " ↑" : " ↓")}
                      </th>
                      <th className="py-2 px-3 text-right text-slate-400 font-medium">持仓</th>
                      <th className="py-2 px-3 text-right text-slate-400 font-medium">因子</th>
                      <th className="py-2 px-3 text-left text-slate-400 font-medium">频率</th>
                      <th className="py-2 px-3 text-left text-slate-400 font-medium cursor-pointer hover:text-slate-200" onClick={() => { if (sortField === "created_at") setSortAsc(!sortAsc); else setSortField("created_at"); }}>
                        创建{sortField === "created_at" && (sortAsc ? " ↑" : " ↓")}
                      </th>
                      <th className="py-2 px-3 text-left text-slate-400 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((s) => (
                      <StrategyRow
                        key={s.id}
                        strategy={s}
                        selected={selectedIds.includes(s.id)}
                        compareMode={compareMode}
                        onSelect={() => toggleSelect(s.id)}
                        onEdit={() => handleEdit(s.id)}
                        onRunBacktest={() => handleRunBacktest(s.id)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
}
