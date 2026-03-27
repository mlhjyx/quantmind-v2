import { useState, useMemo } from "react";
import type { Position } from "@/types/dashboard";

interface Props {
  data: Position[];
  loading: boolean;
}

type SortKey = keyof Position;

function pnlColor(v: number): string {
  if (v > 0) return "text-green-400";
  if (v < 0) return "text-red-400";
  return "text-gray-400";
}

const columns: { key: SortKey; label: string; align: string }[] = [
  { key: "code", label: "代码", align: "text-left" },
  { key: "quantity", label: "持仓", align: "text-right" },
  { key: "avg_cost", label: "成本", align: "text-right" },
  { key: "market_value", label: "市值", align: "text-right" },
  { key: "weight", label: "权重", align: "text-right" },
  { key: "unrealized_pnl", label: "盈亏", align: "text-right" },
  { key: "holding_days", label: "持有天数", align: "text-right" },
];

export default function PositionTable({ data, loading }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("weight");
  const [sortAsc, setSortAsc] = useState(false);

  const sorted = useMemo(() => {
    return [...data].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string") {
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortAsc
        ? (av as number) - (bv as number)
        : (bv as number) - (av as number);
    });
  }, [data, sortKey, sortAsc]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  }

  function sortIndicator(key: SortKey): string {
    if (key !== sortKey) return "";
    return sortAsc ? " \u25B2" : " \u25BC";
  }

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 backdrop-blur-md p-4">
      <h2 className="text-sm font-medium text-gray-300 mb-3">
        持仓列表 ({data.length})
      </h2>
      {loading ? (
        <div className="h-40 flex items-center justify-center text-gray-500">
          Loading...
        </div>
      ) : data.length === 0 ? (
        <div className="h-40 flex items-center justify-center text-gray-500">
          暂无持仓
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    className={`pb-2 px-2 font-medium text-gray-400 cursor-pointer select-none whitespace-nowrap ${col.align}`}
                  >
                    {col.label}
                    {sortIndicator(col.key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((pos) => (
                <tr
                  key={pos.code}
                  className="border-b border-white/5 hover:bg-white/5 transition-colors"
                >
                  <td className="py-2 px-2 text-sky-300 font-mono">
                    {pos.code}
                  </td>
                  <td className="py-2 px-2 text-right text-gray-300">
                    {pos.quantity.toLocaleString()}
                  </td>
                  <td className="py-2 px-2 text-right text-gray-300">
                    {pos.avg_cost.toFixed(2)}
                  </td>
                  <td className="py-2 px-2 text-right text-gray-300">
                    {pos.market_value.toLocaleString()}
                  </td>
                  <td className="py-2 px-2 text-right text-gray-300">
                    {(pos.weight * 100).toFixed(1)}%
                  </td>
                  <td
                    className={`py-2 px-2 text-right font-mono ${pnlColor(pos.unrealized_pnl)}`}
                  >
                    {pos.unrealized_pnl >= 0 ? "+" : ""}
                    {pos.unrealized_pnl.toLocaleString()}
                  </td>
                  <td className="py-2 px-2 text-right text-gray-400">
                    {pos.holding_days}d
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
