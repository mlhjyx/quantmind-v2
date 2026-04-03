import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

interface PMSPosition {
  code: string;
  shares: number;
  entry_price: number;
  peak_price: number;
  current_price: number;
  unrealized_pnl_pct: number;
  drawdown_from_peak_pct: number;
  nearest_protection_level: number | null;
  nearest_protection_gap_pct: number | null;
  status: "safe" | "warning" | "danger";
}

interface PMSConfig {
  enabled: boolean;
  levels: { level: number; min_gain_pct: number; max_drawdown_pct: number }[];
}

function statusColor(status: string) {
  if (status === "safe") return "text-green-400";
  if (status === "warning") return "text-yellow-400";
  return "text-red-400";
}

function statusBg(status: string) {
  if (status === "safe") return "bg-green-500/10 border-green-500/20";
  if (status === "warning") return "bg-yellow-500/10 border-yellow-500/20";
  return "bg-red-500/10 border-red-500/20";
}

function pctFmt(v: number | null | undefined) {
  if (v == null) return "-";
  return `${(v * 100).toFixed(1)}%`;
}

export default function PMS() {
  const { data: posData, isLoading } = useQuery({
    queryKey: ["pms", "positions"],
    queryFn: () => api.get("/api/pms/positions").then((r) => r.data),
    refetchInterval: 60_000,
  });

  const { data: configData } = useQuery({
    queryKey: ["pms", "config"],
    queryFn: () => api.get("/api/pms/config").then((r) => r.data),
  });

  const { data: historyData } = useQuery({
    queryKey: ["pms", "history"],
    queryFn: () => api.get("/api/pms/history").then((r) => r.data),
  });

  const positions: PMSPosition[] = posData?.positions ?? [];
  const config: PMSConfig | undefined = configData;
  const history = historyData?.history ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">利润保护 (PMS)</h1>
          <p className="text-sm text-slate-400 mt-1">
            阶梯利润保护系统 — 三层保护，自动止盈
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`px-3 py-1 rounded-full text-xs font-medium ${
              config?.enabled
                ? "bg-green-500/20 text-green-400"
                : "bg-red-500/20 text-red-400"
            }`}
          >
            {config?.enabled ? "已启用" : "已禁用"}
          </span>
        </div>
      </div>

      {/* Protection Levels */}
      {config && (
        <div className="grid grid-cols-3 gap-4">
          {config.levels.map((lvl) => (
            <div
              key={lvl.level}
              className="bg-slate-800/50 border border-slate-700 rounded-lg p-4"
            >
              <div className="text-xs text-slate-400 mb-1">层级 {lvl.level}</div>
              <div className="text-sm text-white">
                浮盈 &ge; {(lvl.min_gain_pct * 100).toFixed(0)}% 且 回撤 &ge;{" "}
                {(lvl.max_drawdown_pct * 100).toFixed(0)}%
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Positions Table */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700">
          <h2 className="text-sm font-medium text-white">
            持仓监控 ({positions.length}只)
          </h2>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : positions.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">
            暂无持仓数据
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b border-slate-700">
                <th className="px-4 py-2 text-left">代码</th>
                <th className="px-4 py-2 text-right">股数</th>
                <th className="px-4 py-2 text-right">买入价</th>
                <th className="px-4 py-2 text-right">最高价</th>
                <th className="px-4 py-2 text-right">现价</th>
                <th className="px-4 py-2 text-right">浮盈</th>
                <th className="px-4 py-2 text-right">从高回撤</th>
                <th className="px-4 py-2 text-center">保护距离</th>
                <th className="px-4 py-2 text-center">状态</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr
                  key={p.code}
                  className={`border-b border-slate-700/50 ${statusBg(p.status)}`}
                >
                  <td className="px-4 py-2 text-white font-mono">{p.code}</td>
                  <td className="px-4 py-2 text-right text-slate-300">
                    {p.shares.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-300">
                    {p.entry_price.toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-300">
                    {p.peak_price.toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-right text-white font-medium">
                    {p.current_price.toFixed(2)}
                  </td>
                  <td
                    className={`px-4 py-2 text-right font-medium ${
                      p.unrealized_pnl_pct >= 0 ? "text-red-400" : "text-green-400"
                    }`}
                  >
                    {pctFmt(p.unrealized_pnl_pct)}
                  </td>
                  <td className="px-4 py-2 text-right text-yellow-400">
                    {pctFmt(p.drawdown_from_peak_pct)}
                  </td>
                  <td className="px-4 py-2 text-center text-slate-300">
                    {p.nearest_protection_level
                      ? `L${p.nearest_protection_level} ${pctFmt(p.nearest_protection_gap_pct)}`
                      : "-"}
                  </td>
                  <td className={`px-4 py-2 text-center ${statusColor(p.status)}`}>
                    {p.status === "safe"
                      ? "安全"
                      : p.status === "warning"
                        ? "接近"
                        : "触发"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* History */}
      {history.length > 0 && (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700">
            <h2 className="text-sm font-medium text-white">
              触发记录 ({history.length}条)
            </h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b border-slate-700">
                <th className="px-4 py-2 text-left">日期</th>
                <th className="px-4 py-2 text-left">代码</th>
                <th className="px-4 py-2 text-center">层级</th>
                <th className="px-4 py-2 text-right">浮盈</th>
                <th className="px-4 py-2 text-right">回撤</th>
                <th className="px-4 py-2 text-right">触发价</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h: Record<string, unknown>, i: number) => (
                <tr key={i} className="border-b border-slate-700/50">
                  <td className="px-4 py-2 text-slate-300">
                    {String(h.trigger_date ?? "")}
                  </td>
                  <td className="px-4 py-2 text-white font-mono">
                    {String(h.symbol ?? "")}
                  </td>
                  <td className="px-4 py-2 text-center text-yellow-400">
                    L{String(h.pms_level_triggered ?? "")}
                  </td>
                  <td className="px-4 py-2 text-right text-red-400">
                    {pctFmt(h.unrealized_pnl_pct as number)}
                  </td>
                  <td className="px-4 py-2 text-right text-yellow-400">
                    {pctFmt(h.drawdown_from_peak_pct as number)}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-300">
                    {Number(h.trigger_price ?? 0).toFixed(2)}
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
