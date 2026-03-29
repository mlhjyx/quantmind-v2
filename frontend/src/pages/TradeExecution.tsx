import { useState } from "react";
import { Play, Pause } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, TabButtons } from "@/components/shared";
import apiClient from "@/api/client";

// ---- Types ----
interface PendingOrder {
  id: string;
  code: string;
  name: string;
  direction: string;
  quantity: number;
  target_price: number | null;
  trade_date: string | null;
  status: string;
  reject_reason?: string | null;
}

interface ExecutionLogItem {
  id: string;
  code: string;
  name: string;
  direction: string;
  quantity: number;
  fill_price: number | null;
  slippage_bps: number | null;
  status: string;
  executed_at: string | null;
}

interface AlgoConfig {
  strategy_name: string;
  version: number;
  execution_mode: string;
  slippage_model: string;
  slippage_bps: number;
  order_type: string;
  top_n: number;
  rebalance_freq: string;
  turnover_cap: number;
  cash_buffer: number;
  max_single_weight: number;
  max_industry_weight: number;
}

// ---- Mock fallbacks ----
const MOCK_PENDING: PendingOrder[] = [
  { id: "ORD-1247", code: "600519", name: "贵州茅台", direction: "buy", quantity: 200, target_price: 1680.50, trade_date: null, status: "pending" },
  { id: "ORD-1248", code: "002594", name: "比亚迪", direction: "buy", quantity: 500, target_price: 245.80, trade_date: null, status: "pending" },
  { id: "ORD-1249", code: "601318", name: "中国平安", direction: "sell", quantity: 1000, target_price: 48.20, trade_date: null, status: "pending" },
];

const MOCK_LOG: ExecutionLogItem[] = [
  { id: "ORD-1246", code: "000858", name: "五粮液", direction: "buy", quantity: 400, fill_price: 152.28, slippage_bps: 1.3, status: "executed", executed_at: "2026-03-29T14:58:32" },
  { id: "ORD-1245", code: "601899", name: "紫金矿业", direction: "sell", quantity: 2000, fill_price: 15.81, slippage_bps: -0.6, status: "executed", executed_at: "2026-03-29T14:45:18" },
  { id: "ORD-1244", code: "600036", name: "招商银行", direction: "buy", quantity: 800, fill_price: 35.22, slippage_bps: 5.7, status: "executed", executed_at: "2026-03-29T14:30:05" },
  { id: "ORD-1243", code: "002415", name: "海康威视", direction: "buy", quantity: 600, fill_price: 32.08, slippage_bps: -2.5, status: "executed", executed_at: "2026-03-29T13:45:22" },
  { id: "ORD-1242", code: "300750", name: "宁德时代", direction: "buy", quantity: 300, fill_price: 198.65, slippage_bps: 7.5, status: "executed", executed_at: "2026-03-29T11:20:45" },
  { id: "ORD-1241", code: "603259", name: "药明康德", direction: "buy", quantity: 500, fill_price: 52.15, slippage_bps: 0.5, status: "executed", executed_at: "2026-03-29T10:15:33" },
  { id: "ORD-1240", code: "600900", name: "长江电力", direction: "sell", quantity: 1000, fill_price: 29.05, slippage_bps: -17, status: "pending", executed_at: "2026-03-29T09:35:12" },
];

const MOCK_ALGO: AlgoConfig = {
  strategy_name: "v1.1", version: 1, execution_mode: "paper",
  slippage_model: "fixed_bps", slippage_bps: 10, order_type: "market_open",
  top_n: 15, rebalance_freq: "monthly", turnover_cap: 0.5,
  cash_buffer: 0.03, max_single_weight: 0.10, max_industry_weight: 0.25,
};

function dirLabel(d: string) { return d === "buy" ? "买入" : "卖出"; }
function dirColor(d: string) { return d === "buy" ? C.up : C.down; }
function dirBg(d: string) { return d === "buy" ? `${C.up}10` : `${C.down}10`; }

function fmtTime(iso: string | null) {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19).split(" ")[1] ?? "—";
}

function fmtSlippage(bps: number | null) {
  if (bps == null) return "—";
  return (bps >= 0 ? "+" : "") + (bps / 100).toFixed(2) + "%";
}

export default function TradeExecution() {
  const [tab, setTab] = useState("执行中");

  const { data: pendingOrders = MOCK_PENDING, isLoading: loadingPending } = useQuery<PendingOrder[]>({
    queryKey: ["execution-pending"],
    queryFn: () => apiClient.get("/execution/pending-orders").then((r) => r.data),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const { data: executionLog = MOCK_LOG, isLoading: loadingLog } = useQuery<ExecutionLogItem[]>({
    queryKey: ["execution-log-today"],
    queryFn: () => apiClient.get("/execution/log?date=today").then((r) => r.data),
    staleTime: 30_000,
  });

  const { data: algoConfig = MOCK_ALGO } = useQuery<AlgoConfig>({
    queryKey: ["execution-algo-config"],
    queryFn: () => apiClient.get("/execution/algo-config").then((r) => r.data),
    staleTime: 300_000,
  });

  const executingCount = pendingOrders.filter((o) => o.status === "pending").length;
  const rejectedCount = pendingOrders.filter((o) => o.status === "rejected").length;

  // Summary metrics derived from log
  const todayTrades = executionLog.filter((e) => e.executed_at != null).length;
  const todayAmount = executionLog.reduce((sum, e) => sum + (e.fill_price ?? 0) * e.quantity, 0);
  const avgSlippage = executionLog.filter((e) => e.slippage_bps != null).length
    ? executionLog.reduce((s, e) => s + (e.slippage_bps ?? 0), 0) / executionLog.filter((e) => e.slippage_bps != null).length
    : 0;

  return (
    <>
      <PageHeader title="交易执行" titleEn="Trade Execution">
        <TabButtons tabs={["执行中", "历史记录", "算法设置"]} active={tab} onChange={setTab} />
        <div className="flex items-center gap-3" style={{ fontSize: 10 }}>
          <span style={{ color: C.up }}>● 待执行 {executingCount}</span>
          {rejectedCount > 0 && <span style={{ color: C.down }}>● 已拒绝 {rejectedCount}</span>}
        </div>
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3">
        {/* Summary metrics */}
        <div className="grid grid-cols-5 gap-3">
          {[
            { l: "今日交易笔数", v: String(todayTrades), c: C.text1 },
            { l: "今日交易额", v: todayAmount > 0 ? "¥" + (todayAmount / 10000).toFixed(0) + "万" : "—", c: C.text1 },
            { l: "平均滑点", v: fmtSlippage(avgSlippage), c: C.warn },
            { l: "执行模式", v: algoConfig.execution_mode === "paper" ? "模拟盘" : "实盘", c: C.info },
            { l: "调仓频率", v: algoConfig.rebalance_freq === "monthly" ? "月度" : algoConfig.rebalance_freq, c: C.text1 },
          ].map((m, i) => (
            <Card key={i} className="px-3.5 py-2.5">
              <div style={{ fontSize: 9, color: C.text4 }}>{m.l}</div>
              <div style={{ fontSize: 16, fontFamily: C.mono, fontWeight: 700, color: m.c }}>{m.v}</div>
            </Card>
          ))}
        </div>

        {tab === "执行中" && (
          <Card>
            <CardHeader title="待执行订单" titleEn="Pending Orders" />
            {loadingPending ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
            ) : pendingOrders.length === 0 ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>暂无待执行订单</div>
            ) : (
              <div className="p-3 space-y-3">
                {pendingOrders.map((o) => (
                  <div key={o.id} className="rounded-xl p-4" style={{ background: C.bg2, border: `1px solid ${C.border}` }}>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <span style={{ fontSize: 12, fontFamily: C.mono, color: C.text1, fontWeight: 600 }}>{o.id.slice(0, 12)}</span>
                        <span className="px-2 py-0.5 rounded" style={{ fontSize: 10, color: dirColor(o.direction), background: dirBg(o.direction), fontWeight: 500 }}>
                          {dirLabel(o.direction)}
                        </span>
                        <span style={{ fontSize: 12, color: C.text1 }}>{o.name}</span>
                        <span style={{ fontSize: 10, color: C.text4, fontFamily: C.mono }}>{o.code}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded" style={{ fontSize: 10, background: C.accentSoft, color: "#a5b4fc" }}>
                          {o.status === "rejected" ? "已拒绝" : "待执行"}
                        </span>
                        {o.status === "pending" && (
                          <button className="px-2 py-1 rounded cursor-pointer" style={{ fontSize: 10, background: `${C.up}12`, color: C.up }}>
                            <Play size={11} className="inline mr-1" />开始
                          </button>
                        )}
                        {o.status === "executing" && (
                          <button className="px-2 py-1 rounded cursor-pointer" style={{ fontSize: 10, background: `${C.down}12`, color: C.down }}>
                            <Pause size={11} className="inline mr-1" />暂停
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-6" style={{ fontSize: 11, color: C.text3 }}>
                      <span>数量: <span style={{ fontFamily: C.mono, color: C.text1 }}>{o.quantity}股</span></span>
                      {o.target_price && <span>目标价: <span style={{ fontFamily: C.mono, color: C.text1 }}>¥{o.target_price.toFixed(2)}</span></span>}
                      {o.trade_date && <span>日期: <span style={{ fontFamily: C.mono, color: C.text4 }}>{o.trade_date}</span></span>}
                    </div>
                    {o.reject_reason && (
                      <div className="mt-2 px-2.5 py-1.5 rounded-lg" style={{ background: `${C.down}08`, fontSize: 10, color: C.down }}>
                        拒绝原因: {o.reject_reason}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {tab === "历史记录" && (
          <Card>
            <CardHeader title="执行记录" titleEn="Execution History" />
            {loadingLog ? (
              <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>加载中...</div>
            ) : (
              <div className="px-3 pb-2">
                <table className="w-full" style={{ fontSize: 11 }}>
                  <thead>
                    <tr style={{ color: C.text4 }}>
                      <th className="text-left py-2 font-normal">时间</th>
                      <th className="text-left py-2 font-normal">代码</th>
                      <th className="text-left py-2 font-normal">名称</th>
                      <th className="text-center py-2 font-normal">方向</th>
                      <th className="text-right py-2 font-normal">数量</th>
                      <th className="text-right py-2 font-normal">成交价</th>
                      <th className="text-right py-2 font-normal">滑点</th>
                      <th className="text-center py-2 font-normal">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {executionLog.map((e) => (
                      <tr key={e.id} style={{ borderTop: `1px solid ${C.border}` }}>
                        <td className="py-2" style={{ fontFamily: C.mono, color: C.text4 }}>{fmtTime(e.executed_at)}</td>
                        <td className="py-2" style={{ fontFamily: C.mono, color: C.text4 }}>{e.code}</td>
                        <td className="py-2" style={{ color: C.text2 }}>{e.name}</td>
                        <td className="text-center py-2">
                          <span className="px-1.5 py-0.5 rounded" style={{ fontSize: 10, color: dirColor(e.direction), background: dirBg(e.direction) }}>
                            {dirLabel(e.direction)}
                          </span>
                        </td>
                        <td className="text-right py-2" style={{ fontFamily: C.mono, color: C.text2 }}>{e.quantity.toLocaleString()}</td>
                        <td className="text-right py-2" style={{ fontFamily: C.mono, color: C.text1 }}>
                          {e.fill_price != null ? "¥" + e.fill_price.toFixed(2) : "—"}
                        </td>
                        <td className="text-right py-2" style={{ fontFamily: C.mono, color: (e.slippage_bps ?? 0) > 0 ? C.warn : C.up }}>
                          {fmtSlippage(e.slippage_bps)}
                        </td>
                        <td className="text-center py-2">
                          <span className="px-1.5 py-0.5 rounded-full" style={{
                            fontSize: 9,
                            color: e.status === "executed" ? C.up : C.warn,
                            background: e.status === "executed" ? `${C.up}10` : `${C.warn}10`,
                          }}>
                            {e.status === "executed" ? "完成" : "待执行"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {tab === "算法设置" && (
          <div className="grid grid-cols-2 gap-3">
            {[
              { name: "执行模式", value: algoConfig.execution_mode === "paper" ? "模拟盘 (Paper)" : "实盘 (Live)", active: true, desc: "当前策略运行模式", extra: `v${algoConfig.version} · ${algoConfig.strategy_name}` },
              { name: "滑点模型", value: algoConfig.slippage_model, active: true, desc: "订单执行滑点估算方式", extra: `${algoConfig.slippage_bps} bps` },
              { name: "委托方式", value: algoConfig.order_type === "market_open" ? "集合竞价" : algoConfig.order_type, active: true, desc: "订单类型设置", extra: `Top-${algoConfig.top_n} · 换手上限 ${(algoConfig.turnover_cap * 100).toFixed(0)}%` },
              { name: "风险参数", value: `单股 ${(algoConfig.max_single_weight * 100).toFixed(0)}%`, active: true, desc: "仓位权重约束", extra: `行业 ${(algoConfig.max_industry_weight * 100).toFixed(0)}% · 现金 ${(algoConfig.cash_buffer * 100).toFixed(0)}%` },
            ].map((algo) => (
              <Card key={algo.name} className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span style={{ fontSize: 14, fontWeight: 700, color: C.text1 }}>{algo.name}</span>
                    <span className="px-2 py-0.5 rounded-full" style={{ fontSize: 9, color: C.up, background: `${C.up}10` }}>已启用</span>
                  </div>
                  <span style={{ fontSize: 13, fontFamily: C.mono, fontWeight: 600, color: C.accent }}>{algo.value}</span>
                </div>
                <div style={{ fontSize: 11, color: C.text3, marginBottom: 8 }}>{algo.desc}</div>
                <div className="px-2.5 py-1.5 rounded-lg" style={{ background: C.bg2, fontSize: 10, color: C.text4, fontFamily: C.mono }}>{algo.extra}</div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
