/**
 * Execution — QMT交易执行操作台。
 *
 * 三区域布局:
 *   Zone 1 (顶部): QMT状态 + 账户摘要
 *   Zone 2 (左侧): 快捷操作面板
 *   Zone 3 (右侧): 数据面板 (持仓偏差 / 委托 / 成交 / 审计日志)
 */
import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
// useQueryClient removed — invalidation handled by useMutations hooks
import { C } from "@/theme";
import { Card, CardHeader, PageHeader, TabButtons } from "@/components/shared";
import { queryKeys } from "@/lib/queryKeys";
import {
  getQMTStatus,
  getAsset,
  getDrift,
  getOrders,
  getTrades,
  getAuditLog,
  getTradingPaused,
  getAdminToken,
  setAdminToken,
} from "@/api/execution";
import type {
  QMTStatus,
  Asset,
  DriftResult,
  DriftFixPreview,
  Order,
  Trade,
  AuditLogItem,
} from "@/api/execution";
import {
  useTriggerRebalance,
  useFixDriftPreview,
  useFixDriftExecute,
  useCancelAll,
  useCancelOne,
  useEmergencyLiquidate,
  usePauseTrading,
  useResumeTrading,
} from "@/hooks/useMutations";

import { AdminTokenModal, ConfirmModal, DriftPreviewModal, fmtMoney } from "./modals";
import { ActionBtn } from "./ActionBtn";

// ---------------------------------------------------------------------------
// Helpers (used only in this file)
// ---------------------------------------------------------------------------

function statusColor(status: string): string {
  switch (status) {
    case "overbought": return C.up;
    case "missing": return C.warn;
    case "underweight": return C.info;
    default: return C.down;
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case "overbought": return "超买";
    case "missing": return "缺失";
    case "underweight": return "不足";
    default: return "正常";
  }
}

function statusEmoji(status: string): string {
  switch (status) {
    case "overbought": return "\u{1F534}";
    case "missing": return "\u{1F7E1}";
    case "underweight": return "\u{1F7E0}";
    default: return "\u{1F7E2}";
  }
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function Execution() {
  const [tab, setTab] = useState("持仓偏差");
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    title: string; message: string; danger?: boolean; onConfirm: () => void;
  } | null>(null);
  const [driftPreview, setDriftPreview] = useState<DriftFixPreview | null>(null);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  // --- Data queries (unified queryKeys) ---
  const { data: qmtStatus } = useQuery<QMTStatus>({
    queryKey: [...queryKeys.qmtStatus],
    queryFn: getQMTStatus,
    refetchInterval: 5_000,
    staleTime: 3_000,
  });

  const { data: asset } = useQuery<Asset>({
    queryKey: [...queryKeys.executionAsset],
    queryFn: getAsset,
    refetchInterval: 5_000,
    staleTime: 3_000,
  });

  const { data: drift } = useQuery<DriftResult>({
    queryKey: [...queryKeys.executionDrift],
    queryFn: getDrift,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const { data: orders } = useQuery<Order[]>({
    queryKey: [...queryKeys.executionOrders],
    queryFn: getOrders,
    refetchInterval: 5_000,
    staleTime: 3_000,
    enabled: qmtStatus?.state === "connected",
    retry: false,
  });

  const { data: trades } = useQuery<Trade[]>({
    queryKey: [...queryKeys.executionTrades],
    queryFn: getTrades,
    refetchInterval: 10_000,
    staleTime: 5_000,
    enabled: qmtStatus?.state === "connected",
    retry: false,
  });

  const { data: auditLog } = useQuery<AuditLogItem[]>({
    queryKey: [...queryKeys.executionAuditLog],
    queryFn: () => getAuditLog(50),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  const { data: isPaused } = useQuery<boolean>({
    queryKey: [...queryKeys.tradingPaused],
    queryFn: getTradingPaused,
    staleTime: 5_000,
  });

  // --- Toast helper ---
  const showToast = useCallback((msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  }, []);

  // --- Admin token gate ---
  const withAuth = useCallback((action: () => void) => {
    if (!getAdminToken()) {
      setPendingAction(() => action);
      setShowTokenModal(true);
    } else {
      action();
    }
  }, []);

  const handleTokenSubmit = useCallback((token: string) => {
    setAdminToken(token);
    setShowTokenModal(false);
    if (pendingAction) {
      pendingAction();
      setPendingAction(null);
    }
  }, [pendingAction]);

  // --- Mutations (unified, with cross-page invalidation) ---
  const cancelAllMutBase = useCancelAll();
  const cancelAllMut = {
    ...cancelAllMutBase,
    mutate: () => cancelAllMutBase.mutate(undefined, {
      onSuccess: (d) => showToast(`已撤销 ${d.cancelled}/${d.total_pending} 笔挂单`, true),
      onError: (e: Error) => showToast(`撤单失败: ${e.message}`, false),
    }),
  };

  const cancelOneMutBase = useCancelOne();
  const cancelOneMut = {
    ...cancelOneMutBase,
    mutate: (orderId: number) => cancelOneMutBase.mutate(orderId, {
      onSuccess: () => showToast("撤单成功", true),
      onError: (e: Error) => showToast(`撤单失败: ${e.message}`, false),
    }),
  };

  const rebalanceMutBase = useTriggerRebalance();
  const rebalanceMut = {
    ...rebalanceMutBase,
    mutate: () => rebalanceMutBase.mutate(undefined, {
      onSuccess: (d) => showToast(d.message, true),
      onError: (e: Error) => showToast(`调仓失败: ${e.message}`, false),
    }),
  };

  const fixDriftPreviewMutBase = useFixDriftPreview();
  const fixDriftPreviewMut = {
    ...fixDriftPreviewMutBase,
    mutate: () => fixDriftPreviewMutBase.mutate(undefined, {
      onSuccess: (d) => setDriftPreview(d),
      onError: (e: Error) => showToast(`预览失败: ${e.message}`, false),
    }),
  };

  const fixDriftExecMutBase = useFixDriftExecute();
  const fixDriftExecMut = {
    ...fixDriftExecMutBase,
    mutate: () => fixDriftExecMutBase.mutate(undefined, {
      onSuccess: (d) => {
        setDriftPreview(null);
        showToast(`偏差修复: 卖${d.sell_count}只 买${d.buy_count}只`, true);
      },
      onError: (e: Error) => showToast(`修复失败: ${e.message}`, false),
    }),
  };

  const emergencyMutBase = useEmergencyLiquidate();
  const emergencyMut = {
    ...emergencyMutBase,
    mutate: () => emergencyMutBase.mutate(undefined, {
      onSuccess: (d) => showToast(`紧急清仓: ${d.position_count}只`, true),
      onError: (e: Error) => showToast(`清仓失败: ${e.message}`, false),
    }),
  };

  const pauseMutBase = usePauseTrading();
  const pauseMut = {
    ...pauseMutBase,
    mutate: () => pauseMutBase.mutate(undefined, {
      onSuccess: () => showToast("自动交易已暂停", true),
      onError: (e: Error) => showToast(`暂停失败: ${e.message}`, false),
    }),
  };

  const resumeMutBase = useResumeTrading();
  const resumeMut = {
    ...resumeMutBase,
    mutate: () => resumeMutBase.mutate(undefined, {
      onSuccess: () => showToast("自动交易已恢复", true),
      onError: (e: Error) => showToast(`恢复失败: ${e.message}`, false),
    }),
  };

  // --- Derived ---
  const isConnected = qmtStatus?.state === "connected";
  const totalAsset = asset?.total_asset ?? 0;
  const cash = asset?.cash ?? 0;
  const frozenCash = asset?.frozen_cash ?? 0;
  const todayPnl = totalAsset > 0 && qmtStatus?.account_asset
    ? 0 // Placeholder — real PnL needs yesterday's NAV
    : 0;
  const driftItems = drift?.items ?? [];
  const safeOrders = orders ?? [];
  const safeTrades = trades ?? [];
  const safeAudit = auditLog ?? [];

  // --- QMT order status label ---
  const orderStatusLabel = (s: number): string => {
    const map: Record<number, string> = {
      48: "已成", 50: "已撤", 51: "部撤", 52: "已报", 53: "部成",
      54: "废单", 55: "待报", 56: "待撤",
    };
    return map[s] ?? String(s);
  };
  const isOrderPending = (s: number) => ![48, 50, 51, 54, 57].includes(s);

  return (
    <>
      <PageHeader title="交易执行" titleEn="Execution Control">
        <TabButtons
          tabs={["持仓偏差", "今日委托", "今日成交", "操作日志"]}
          active={tab}
          onChange={setTab}
        />
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3">
        {/* ================================================================
            Zone 1 — 顶部状态栏
        ================================================================ */}
        <Card className="px-5 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <span
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ background: isConnected ? C.down : C.up }}
                />
                <span style={{ fontSize: 12, color: C.text2, fontWeight: 600 }}>
                  QMT: {isConnected ? "已连接" : qmtStatus?.state ?? "未知"}
                </span>
                {qmtStatus?.account_id && (
                  <span style={{ fontSize: 11, color: C.text4, fontFamily: "monospace" }}>
                    {qmtStatus.account_id}
                  </span>
                )}
              </div>
              {isPaused && (
                <span className="px-2 py-0.5 rounded" style={{ fontSize: 10, background: `${C.warn}20`, color: C.warn }}>
                  交易已暂停
                </span>
              )}
            </div>
            <div className="flex items-center gap-6" style={{ fontSize: 12 }}>
              <div>
                <span style={{ color: C.text4 }}>总资产 </span>
                <span style={{ color: C.text1, fontFamily: "monospace", fontWeight: 700 }}>
                  ¥{fmtMoney(totalAsset)}
                </span>
              </div>
              <div>
                <span style={{ color: C.text4 }}>可用 </span>
                <span style={{ color: C.text1, fontFamily: "monospace" }}>¥{fmtMoney(cash)}</span>
              </div>
              <div>
                <span style={{ color: C.text4 }}>冻结 </span>
                <span style={{ color: C.text3, fontFamily: "monospace" }}>¥{fmtMoney(frozenCash)}</span>
              </div>
              {todayPnl !== 0 && (
                <div>
                  <span style={{ color: C.text4 }}>今日 </span>
                  <span style={{ color: todayPnl >= 0 ? C.up : C.down, fontFamily: "monospace" }}>
                    {todayPnl >= 0 ? "+" : ""}{fmtMoney(todayPnl)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* ================================================================
            Zone 2+3 — 左侧操作 + 右侧数据
        ================================================================ */}
        <div className="flex gap-3" style={{ minHeight: 500 }}>
          {/* --- Left: 操作面板 --- */}
          <div className="flex-shrink-0" style={{ width: 200 }}>
            <Card className="p-4 space-y-3 h-full">
              <div style={{ fontSize: 12, fontWeight: 700, color: C.text2, marginBottom: 4 }}>快捷操作</div>

              <ActionBtn
                label="触发调仓"
                disabled={!isConnected}
                loading={rebalanceMut.isPending}
                onClick={() => withAuth(() =>
                  setConfirmModal({
                    title: "触发调仓",
                    message: "将触发完整的信号→执行流程。确定要手动调仓吗？",
                    onConfirm: () => { setConfirmModal(null); rebalanceMut.mutate(); },
                  })
                )}
              />

              <ActionBtn
                label="偏差修复"
                disabled={!isConnected}
                loading={fixDriftPreviewMut.isPending}
                onClick={() => withAuth(() => fixDriftPreviewMut.mutate())}
              />

              <ActionBtn
                label="撤全部挂单"
                disabled={!isConnected}
                loading={cancelAllMut.isPending}
                onClick={() => withAuth(() =>
                  setConfirmModal({
                    title: "撤销所有挂单",
                    message: `确定要撤销所有未完成委托吗？`,
                    onConfirm: () => { setConfirmModal(null); cancelAllMut.mutate(); },
                  })
                )}
              />

              {isPaused ? (
                <ActionBtn
                  label="恢复交易"
                  color={C.down}
                  loading={resumeMut.isPending}
                  onClick={() => withAuth(() => resumeMut.mutate())}
                />
              ) : (
                <ActionBtn
                  label="暂停交易"
                  color={C.warn}
                  loading={pauseMut.isPending}
                  onClick={() => withAuth(() => pauseMut.mutate())}
                />
              )}

              <div style={{ borderTop: `1px solid ${C.border}`, margin: "8px 0" }} />
              <div style={{ fontSize: 10, color: C.text4, marginBottom: 4 }}>危险操作</div>

              <ActionBtn
                label="紧急清仓"
                color={C.up}
                disabled={!isConnected}
                loading={emergencyMut.isPending}
                onClick={() => withAuth(() =>
                  setConfirmModal({
                    title: "紧急清仓",
                    message: "将卖出所有可卖持仓！此操作不可撤销。请输入 CONFIRM 确认。",
                    danger: true,
                    onConfirm: () => { setConfirmModal(null); emergencyMut.mutate(); },
                  })
                )}
              />
            </Card>
          </div>

          {/* --- Right: 数据面板 --- */}
          <div className="flex-1 min-w-0">
            {/* Tab: 持仓偏差 */}
            {tab === "持仓偏差" && (
              <Card>
                <CardHeader title="持仓偏差" titleEn="Position Drift" />
                {drift?.funding_analysis && (
                  <div className="px-4 pb-2 flex gap-4" style={{ fontSize: 10, color: C.text3 }}>
                    <span>信号日期: <span style={{ color: C.text2 }}>{drift.signal_date ?? "—"}</span></span>
                    <span>正常 <span style={{ color: C.down }}>{drift.summary.normal}</span></span>
                    <span>超买 <span style={{ color: C.up }}>{drift.summary.overbought}</span></span>
                    <span>缺失 <span style={{ color: C.warn }}>{drift.summary.missing}</span></span>
                    <span>不足 <span style={{ color: C.info }}>{drift.summary.underweight}</span></span>
                    <span className="ml-auto">卖出可释放 <span style={{ color: C.down }}>{fmtMoney(drift.funding_analysis.overbought_release)}</span></span>
                    <span>可买 <span style={{ color: C.text2 }}>{drift.funding_analysis.can_buy_count}/{drift.funding_analysis.missing_count}只</span></span>
                  </div>
                )}
                {driftItems.length === 0 ? (
                  <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>暂无偏差数据</div>
                ) : (
                  <div className="px-3 pb-2">
                    <table className="w-full" style={{ fontSize: 11 }}>
                      <thead>
                        <tr style={{ color: C.text4 }}>
                          <th className="text-left py-2 font-normal">代码</th>
                          <th className="text-left py-2 font-normal">名称</th>
                          <th className="text-right py-2 font-normal">信号目标</th>
                          <th className="text-right py-2 font-normal">实际持仓</th>
                          <th className="text-right py-2 font-normal">可卖</th>
                          <th className="text-right py-2 font-normal">偏差</th>
                          <th className="text-center py-2 font-normal">状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {driftItems.map((d) => (
                          <tr key={d.code} style={{ borderTop: `1px solid ${C.border}` }}>
                            <td className="py-1.5" style={{ fontFamily: "monospace", color: C.text3 }}>{d.code}</td>
                            <td className="py-1.5" style={{ color: C.text2 }}>{d.name}</td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text2 }}>
                              {fmtMoney(d.target_value)}
                            </td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text1 }}>
                              {d.actual_volume.toLocaleString()}
                            </td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: d.can_use_volume < d.actual_volume ? C.warn : C.text3 }}>
                              {d.can_use_volume.toLocaleString()}
                            </td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: statusColor(d.status) }}>
                              {d.deviation_pct > 0 ? "+" : ""}{d.deviation_pct}%
                            </td>
                            <td className="text-center py-1.5">
                              <span className="px-1.5 py-0.5 rounded-full" style={{
                                fontSize: 9,
                                color: statusColor(d.status),
                                background: `${statusColor(d.status)}15`,
                              }}>
                                {statusEmoji(d.status)} {statusLabel(d.status)}
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

            {/* Tab: 今日委托 */}
            {tab === "今日委托" && (
              <Card>
                <CardHeader title="今日委托" titleEn="Today Orders" />
                {!isConnected ? (
                  <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>QMT未连接</div>
                ) : safeOrders.length === 0 ? (
                  <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>暂无委托</div>
                ) : (
                  <div className="px-3 pb-2">
                    <table className="w-full" style={{ fontSize: 11 }}>
                      <thead>
                        <tr style={{ color: C.text4 }}>
                          <th className="text-left py-2 font-normal">委托号</th>
                          <th className="text-left py-2 font-normal">代码</th>
                          <th className="text-center py-2 font-normal">方向</th>
                          <th className="text-right py-2 font-normal">委托量</th>
                          <th className="text-right py-2 font-normal">委托价</th>
                          <th className="text-right py-2 font-normal">成交量</th>
                          <th className="text-center py-2 font-normal">状态</th>
                          <th className="text-center py-2 font-normal">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {safeOrders.map((o) => (
                          <tr key={o.order_id} style={{ borderTop: `1px solid ${C.border}` }}>
                            <td className="py-1.5" style={{ fontFamily: "monospace", color: C.text4, fontSize: 10 }}>{o.order_id}</td>
                            <td className="py-1.5" style={{ fontFamily: "monospace", color: C.text2 }}>{o.code}</td>
                            <td className="text-center py-1.5">
                              <span style={{ color: o.order_type === 23 ? C.up : C.down, fontSize: 10 }}>
                                {o.order_type === 23 ? "买入" : "卖出"}
                              </span>
                            </td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text1 }}>{o.volume}</td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text2 }}>{o.price.toFixed(2)}</td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text3 }}>{o.traded_volume}</td>
                            <td className="text-center py-1.5">
                              <span className="px-1.5 py-0.5 rounded-full" style={{
                                fontSize: 9,
                                color: o.status === 48 ? C.down : C.warn,
                                background: o.status === 48 ? `${C.down}10` : `${C.warn}10`,
                              }}>
                                {orderStatusLabel(o.status)}
                              </span>
                            </td>
                            <td className="text-center py-1.5">
                              {isOrderPending(o.status) && (
                                <button
                                  className="px-2 py-0.5 rounded cursor-pointer"
                                  style={{ fontSize: 10, background: `${C.up}12`, color: C.up }}
                                  onClick={() => withAuth(() => cancelOneMut.mutate(o.order_id))}
                                >
                                  撤单
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            )}

            {/* Tab: 今日成交 */}
            {tab === "今日成交" && (
              <Card>
                <CardHeader title="今日成交" titleEn="Today Trades" />
                {!isConnected ? (
                  <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>QMT未连接</div>
                ) : safeTrades.length === 0 ? (
                  <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>暂无成交</div>
                ) : (
                  <div className="px-3 pb-2">
                    <table className="w-full" style={{ fontSize: 11 }}>
                      <thead>
                        <tr style={{ color: C.text4 }}>
                          <th className="text-left py-2 font-normal">委托号</th>
                          <th className="text-left py-2 font-normal">代码</th>
                          <th className="text-center py-2 font-normal">方向</th>
                          <th className="text-right py-2 font-normal">成交价</th>
                          <th className="text-right py-2 font-normal">成交量</th>
                          <th className="text-right py-2 font-normal">成交额</th>
                        </tr>
                      </thead>
                      <tbody>
                        {safeTrades.map((t, i) => (
                          <tr key={`${t.order_id}-${i}`} style={{ borderTop: `1px solid ${C.border}` }}>
                            <td className="py-1.5" style={{ fontFamily: "monospace", color: C.text4, fontSize: 10 }}>{t.order_id}</td>
                            <td className="py-1.5" style={{ fontFamily: "monospace", color: C.text2 }}>{t.code}</td>
                            <td className="text-center py-1.5">
                              <span style={{ color: t.order_type === 23 ? C.up : C.down, fontSize: 10 }}>
                                {t.order_type === 23 ? "买入" : "卖出"}
                              </span>
                            </td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text1 }}>¥{t.price.toFixed(2)}</td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text2 }}>{t.volume.toLocaleString()}</td>
                            <td className="py-1.5 text-right" style={{ fontFamily: "monospace", color: C.text2 }}>¥{fmtMoney(t.amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            )}

            {/* Tab: 操作日志 */}
            {tab === "操作日志" && (
              <Card>
                <CardHeader title="操作日志" titleEn="Audit Log" />
                {safeAudit.length === 0 ? (
                  <div className="p-6 text-center" style={{ fontSize: 12, color: C.text4 }}>暂无操作记录</div>
                ) : (
                  <div className="px-3 pb-2">
                    <table className="w-full" style={{ fontSize: 11 }}>
                      <thead>
                        <tr style={{ color: C.text4 }}>
                          <th className="text-left py-2 font-normal">时间</th>
                          <th className="text-left py-2 font-normal">操作</th>
                          <th className="text-left py-2 font-normal">详情</th>
                          <th className="text-center py-2 font-normal">结果</th>
                        </tr>
                      </thead>
                      <tbody>
                        {safeAudit.map((a) => (
                          <tr key={a.id} style={{ borderTop: `1px solid ${C.border}` }}>
                            <td className="py-1.5" style={{ fontFamily: "monospace", color: C.text4, fontSize: 10 }}>
                              {a.timestamp?.replace("T", " ").slice(0, 19) ?? "—"}
                            </td>
                            <td className="py-1.5" style={{ color: C.text2 }}>{a.action}</td>
                            <td className="py-1.5" style={{ color: C.text3, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {a.detail || "—"}
                            </td>
                            <td className="text-center py-1.5">
                              <span className="px-1.5 py-0.5 rounded-full" style={{
                                fontSize: 9,
                                color: a.result === "success" ? C.down : a.result === "error" ? C.up : C.warn,
                                background: a.result === "success" ? `${C.down}10` : a.result === "error" ? `${C.up}10` : `${C.warn}10`,
                              }}>
                                {a.result}
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
          </div>
        </div>
      </div>

      {/* ================================================================
          Modals
      ================================================================ */}
      {showTokenModal && (
        <AdminTokenModal
          onSubmit={handleTokenSubmit}
          onCancel={() => { setShowTokenModal(false); setPendingAction(null); }}
        />
      )}
      {confirmModal && (
        <ConfirmModal
          title={confirmModal.title}
          message={confirmModal.message}
          danger={confirmModal.danger}
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}
      {driftPreview && (
        <DriftPreviewModal
          preview={driftPreview}
          onExecute={() => fixDriftExecMut.mutate()}
          onCancel={() => setDriftPreview(null)}
        />
      )}
      {toast && (
        <div
          className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-lg shadow-lg"
          style={{
            background: toast.ok ? `${C.down}20` : `${C.up}20`,
            color: toast.ok ? C.down : C.up,
            fontSize: 12,
            border: `1px solid ${toast.ok ? C.down : C.up}40`,
          }}
        >
          {toast.msg}
        </div>
      )}
    </>
  );
}
