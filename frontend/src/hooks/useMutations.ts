/**
 * Unified mutation hooks with cross-page invalidation.
 *
 * Each mutation defines which queryKeys to invalidate on success,
 * ensuring related pages auto-refresh without manual coordination.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryKeys";
import {
  cancelAllOrders,
  cancelOrder,
  fixDriftPreview,
  fixDriftExecute,
  triggerRebalance,
  emergencyLiquidate,
  pauseTrading,
  resumeTrading,
} from "@/api/execution";

// ---------------------------------------------------------------------------
// Execution mutations
// ---------------------------------------------------------------------------

/** 触发调仓 → 刷新: portfolio, orders, drift, audit */
export function useTriggerRebalance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: triggerRebalance,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.portfolio] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionOrders] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionDrift] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionAuditLog] });
    },
  });
}

/** 偏差修复预览 — 无副作用，不invalidate */
export function useFixDriftPreview() {
  return useMutation({ mutationFn: fixDriftPreview });
}

/** 偏差修复执行 → 刷新: portfolio, orders, trades, drift, audit */
export function useFixDriftExecute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => fixDriftExecute(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.portfolio] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionOrders] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionTrades] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionDrift] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionAuditLog] });
    },
  });
}

/** 撤全部挂单 → 刷新: orders, audit */
export function useCancelAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: cancelAllOrders,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.executionOrders] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionAuditLog] });
    },
  });
}

/** 撤单笔 → 刷新: orders */
export function useCancelOne() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderId: number) => cancelOrder(orderId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.executionOrders] });
    },
  });
}

/** 紧急清仓 → 刷新: portfolio, orders, trades, drift, audit */
export function useEmergencyLiquidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: emergencyLiquidate,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.portfolio] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionOrders] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionTrades] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionDrift] });
      qc.invalidateQueries({ queryKey: [...queryKeys.executionAuditLog] });
    },
  });
}

/** 暂停交易 → 刷新: paused状态 */
export function usePauseTrading() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: pauseTrading,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.tradingPaused] });
    },
  });
}

/** 恢复交易 → 刷新: paused状态 */
export function useResumeTrading() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: resumeTrading,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.tradingPaused] });
    },
  });
}
