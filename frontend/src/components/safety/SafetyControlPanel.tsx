/**
 * SafetyControlPanel — 紧急控制面板 (RiskManagement 4th tab).
 *
 * Frontend Design v3 §2.2 — 6 CC-only ops 首批前端化:
 *   - Circuit Breaker state visualization (L0-L4 ladder)
 *   - L4 STAGED force-reset (HIGH tier confirm)
 *   - 显示 L4 STAGED 状态 + 等待人工 approve 提示
 *   - env mode 提示 (read-only, EnvStateBanner 已显示)
 *
 * 业务目的 (LL-183 教训): backend kill-switch + force-reset 全部 CC-only,
 * 用户应有 UI 入口可见 + 安全 confirm flow. CRIT ops 仍 CC-only (e.g. env_flip).
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shield, AlertCircle, Zap, RefreshCw, History, ShieldCheck, ShieldX } from "lucide-react";
import { C } from "@/theme";
import { Card, CardHeader } from "@/components/shared";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import type { CircuitBreakerState } from "@/types/dashboard";
import {
  approveL4Recovery,
  fetchCircuitBreakerState,
  forceResetCircuitBreaker,
  requestL4Recovery,
} from "@/api/risk";
import { fetchEnvState, type EnvState, getPaperStrategyId } from "@/api/system";
import { isAdminAuthed } from "@/api/execution";

// iter 137 W2-F F2 closure — L4 Recovery + Approve flow wiring.
// Backend SSOT: backend/app/api/risk.py
//   - POST /api/risk/l4-recovery/{strategy_id} (line 206): operator requests
//     L4 recovery → service creates approval_queue row → returns {approval_id, status}
//   - POST /api/risk/l4-approve/{approval_id} (line 239): reviewer approves/rejects
//     → returns new state (approved) or status='rejected'
//
// iter 137 reviewer P0 fix — DEFAULT_STRATEGY_ID="default" 不是 UUID, backend
// `risk.py:229` `_parse_uuid("default", ...)` 必 raise ValueError → HTTP 400.
// Use real UUID via GET /api/system/settings/paper-strategy-id (iter 39 pattern,
// canonical sibling = ReportCenter.tsx:101-113).

interface SafetyPanelData {
  cb: CircuitBreakerState | null;
  env: EnvState | null;
  adminAuthed: boolean;
}

interface LevelDef {
  level: number;
  name: string;
  desc: string;
  color: string;
}

const LEVEL_LADDER: LevelDef[] = [
  { level: 0, name: "NORMAL", desc: "正常运行", color: "#22c55e" },
  { level: 1, name: "L1_WARN", desc: "Warning · 通知保持", color: "#ffb020" },
  { level: 2, name: "L2_REDUCE", desc: "减仓 · 仓位倍数 0.5", color: "#fb923c" },
  { level: 3, name: "L3_HALT", desc: "停止下单 · 持仓保持", color: "#ef4444" },
  { level: 4, name: "L4_LIQUIDATE", desc: "清仓 · STAGED 人工确认", color: "#dc2626" },
];

export function SafetyControlPanel() {
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [actionMsg, setActionMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // iter 137 W2-F F2: L4 recovery + approve state
  const [showRequestRecovery, setShowRequestRecovery] = useState(false);
  const [showApproveRecovery, setShowApproveRecovery] = useState<"approve" | "reject" | null>(null);
  const [pendingApprovalId, setPendingApprovalId] = useState<string | null>(null);

  // iter 137 reviewer P0 fix — fetch real paper_strategy_id UUID for L4 recovery
  // POST path (replaces "default" hardcoded which failed backend _parse_uuid).
  // Sibling pattern: ReportCenter.tsx:101-113 (iter 39 canonical).
  const { data: paperSid } = useQuery({
    queryKey: ["system-paper-strategy-id"],
    queryFn: () => getPaperStrategyId(),
    staleTime: 60 * 60 * 1000, // strategy_id rarely changes; 1h cache OK
  });
  const strategyId =
    paperSid?.configured && paperSid.paper_strategy_id ? paperSid.paper_strategy_id : null;

  // Session 58 round-4 ADR-084 Phase 1: setInterval → react-query (uniform lifecycle).
  // The circuit-breaker endpoint requires a UUID strategy path; do not mask that
  // call into "default" or null when PAPER_STRATEGY_ID is configured.
  const { data, isLoading, refetch } = useQuery<SafetyPanelData>({
    queryKey: ["safety-control-panel", strategyId],
    queryFn: async () => {
      const [cb, env, authed] = await Promise.all([
        strategyId ? fetchCircuitBreakerState(strategyId) : Promise.resolve(null),
        fetchEnvState().catch(() => null),
        isAdminAuthed().catch(() => false),
      ]);
      return { cb, env, adminAuthed: authed };
    },
    enabled: paperSid !== undefined,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const state = data?.cb ?? null;
  const envState = data?.env ?? null;
  const adminAuthed = data?.adminAuthed ?? null;
  const loading = isLoading;
  const load = () => void refetch();

  const handleForceReset = async (meta: { reason?: string }) => {
    if (!strategyId) {
      setShowResetConfirm(false);
      setActionMsg({
        ok: false,
        text: "无法获取策略ID (PAPER_STRATEGY_ID 未配置, 请检查后端 settings)",
      });
      setTimeout(() => setActionMsg(null), 8000);
      return;
    }
    setShowResetConfirm(false);
    try {
      await forceResetCircuitBreaker(
        strategyId,
        meta.reason ?? "manual reset via frontend SafetyControlPanel",
      );
      setActionMsg({ ok: true, text: "Force-reset 成功, 刷新中..." });
      void load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "请求失败";
      setActionMsg({ ok: false, text: `Force-reset 失败: ${msg}` });
    }
    setTimeout(() => setActionMsg(null), 5000);
  };

  // iter 137 W2-F F2 — L4 recovery request (operator step 1).
  // Backend: POST /risk/l4-recovery/{strategy_id} L4RecoveryRequest{reviewer_note}
  // → returns {approval_id, status: "pending"}. Frontend stores approval_id in
  // component state for the subsequent approve/reject step. Pre-condition:
  // currentLevel === 4 (backend raises 400 ValueError if not L4_STOPPED).
  //
  // iter 137 reviewer M3 fix — modal close moved INSIDE try after success
  // (sibling PR #485 M1 / iter 136e canonical). On error, modal stays open
  // with reason text intact for retry.
  const handleRequestRecovery = async (meta: { reason?: string }) => {
    if (!strategyId) {
      setActionMsg({
        ok: false,
        text: "无法获取策略ID (PAPER_STRATEGY_ID 未配置, 请检查 .env 或后端 settings)",
      });
      setTimeout(() => setActionMsg(null), 8000);
      return;
    }
    try {
      const res = await requestL4Recovery(
        strategyId,
        meta.reason ?? "L4 recovery request from operator UI",
      );
      setPendingApprovalId(res.approval_id);
      setShowRequestRecovery(false); // close modal only on success
      setActionMsg({
        ok: true,
        text: `L4 恢复请求已创建: ${res.approval_id.slice(0, 8)}… (待 admin 审批)`,
      });
      void load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "请求失败";
      setActionMsg({ ok: false, text: `L4 恢复请求失败: ${msg}` });
    }
    setTimeout(() => setActionMsg(null), 8000);
  };

  // iter 137 W2-F F2 — L4 recovery approve/reject (admin step 2).
  // Backend: POST /risk/l4-approve/{approval_id} L4ApproveRequest{approved, reviewer_note}
  // → on approved=true returns new_state; on approved=false returns status='rejected'.
  // Reverse-decision-权 enforced at backend service layer (ADR-027); admin token
  // required (verify_admin_token Depends, risk.py:243-244).
  //
  // iter 137 reviewer M3 fix — modal close moved INSIDE try after success
  // (sibling PR #485 M1 / iter 136e canonical). On error, modal stays open
  // with reason text intact for retry.
  const handleApproveRecovery = async (meta: { reason?: string }) => {
    if (!pendingApprovalId || !showApproveRecovery) return;
    const approved = showApproveRecovery === "approve";
    try {
      const res = await approveL4Recovery(
        pendingApprovalId,
        approved,
        meta.reason ?? "",
      );
      const verdict = approved ? "已批准" : "已拒绝";
      const newLvl = res.new_state?.level;
      setActionMsg({
        ok: true,
        text: `L4 恢复${verdict}${newLvl != null ? ` (新状态: L${newLvl})` : ""}`,
      });
      setPendingApprovalId(null);
      setShowApproveRecovery(null); // close modal only on success
      void load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "请求失败";
      setActionMsg({ ok: false, text: `L4 ${approved ? "批准" : "拒绝"} 失败: ${msg}` });
    }
    setTimeout(() => setActionMsg(null), 8000);
  };

  const currentLevel = state?.level ?? 0;
  const levelDef = LEVEL_LADDER[currentLevel] ?? LEVEL_LADDER[0]!;
  const isElevated = currentLevel >= 2;
  const needsManualApprove = state?.requires_manual_approval ?? false;

  return (
    <div className="space-y-3">
      {/* Action message toast */}
      {actionMsg && (
        <div
          className="px-4 py-2 rounded-lg"
          style={{
            background: actionMsg.ok ? `${C.down}15` : `${C.up}15`,
            border: `1px solid ${actionMsg.ok ? C.down : C.up}40`,
            fontSize: 12,
            color: actionMsg.ok ? C.down : C.up,
          }}
        >
          {actionMsg.text}
        </div>
      )}

      {/* Row 1: Circuit breaker state + actions */}
      <div className="grid grid-cols-12 gap-3">
        <Card className="col-span-8">
          <CardHeader title="熔断状态" titleEn="Circuit Breaker" />
          <div className="p-4">
            {loading && !state ? (
              <div className="text-center py-4" style={{ fontSize: 12, color: C.text4 }}>
                加载中...
              </div>
            ) : (
              <>
                {/* Current state highlight */}
                <div
                  className="flex items-center gap-3 px-4 py-3 rounded-lg mb-4"
                  style={{
                    background: `${levelDef.color}12`,
                    border: `1px solid ${levelDef.color}40`,
                  }}
                >
                  <Shield size={18} color={levelDef.color} />
                  <div className="flex-1">
                    <div style={{ fontSize: 14, color: levelDef.color, fontWeight: 700 }}>
                      L{currentLevel} · {levelDef.name}
                    </div>
                    <div style={{ fontSize: 11, color: C.text3, marginTop: 2 }}>
                      {levelDef.desc}
                    </div>
                  </div>
                  <div className="text-right" style={{ fontSize: 10, color: C.text4 }}>
                    <div>仓位倍数: {state?.position_multiplier?.toFixed(2) ?? "—"}</div>
                    <div>
                      can_rebalance:{" "}
                      <span
                        style={{
                          color: state?.can_rebalance ? C.up : C.down,
                          fontFamily: C.mono,
                        }}
                      >
                        {String(state?.can_rebalance ?? "—")}
                      </span>
                    </div>
                  </div>
                </div>

                {/* L0-L4 ladder */}
                <div className="grid grid-cols-5 gap-2">
                  {LEVEL_LADDER.map((def) => {
                    const active = def.level === currentLevel;
                    const passed = def.level < currentLevel;
                    return (
                      <div
                        key={def.level}
                        className="text-center rounded-lg p-2"
                        style={{
                          background: active ? `${def.color}20` : C.bg2,
                          border: `1px solid ${active ? def.color : passed ? `${def.color}40` : C.border}`,
                          opacity: !active && !passed ? 0.5 : 1,
                        }}
                      >
                        <div
                          style={{
                            fontSize: 10,
                            color: active ? def.color : passed ? def.color : C.text4,
                            fontWeight: active ? 700 : 500,
                          }}
                        >
                          L{def.level}
                        </div>
                        <div
                          style={{
                            fontSize: 9,
                            color: active ? def.color : C.text4,
                            marginTop: 2,
                            fontFamily: C.mono,
                          }}
                        >
                          {def.name.split("_")[1] ?? def.name}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Trigger reason if elevated */}
                {isElevated && state?.trigger_reason && (
                  <div
                    className="mt-3 px-3 py-2 rounded"
                    style={{
                      background: `${levelDef.color}08`,
                      border: `1px solid ${levelDef.color}30`,
                      fontSize: 11,
                      color: C.text2,
                    }}
                  >
                    <div style={{ color: C.text4, marginBottom: 2 }}>触发原因:</div>
                    {state.trigger_reason}
                  </div>
                )}

                {/* Recovery streak if has any */}
                {state?.recovery_streak_days != null && state.recovery_streak_days > 0 && (
                  <div className="mt-2 flex items-center gap-3" style={{ fontSize: 11, color: C.text3 }}>
                    <History size={12} />
                    <span>
                      恢复积累: {state.recovery_streak_days} 天 / 累计回报{" "}
                      {(state.recovery_streak_return * 100).toFixed(2)}%
                    </span>
                  </div>
                )}
              </>
            )}
          </div>
        </Card>

        {/* Action panel */}
        <Card className="col-span-4">
          <CardHeader title="紧急操作" titleEn="Emergency Ops" />
          <div className="p-4 space-y-2">
            {/* ENV info */}
            <div
              className="px-3 py-2 rounded mb-2"
              style={{
                background: C.bg2,
                border: `1px solid ${C.border}`,
                fontSize: 11,
                color: C.text3,
              }}
            >
              <div>
                ENV:{" "}
                <span
                  style={{
                    fontFamily: C.mono,
                    color: envState?.mode === "live" ? C.up : C.down,
                  }}
                >
                  {envState?.mode ?? "—"}
                </span>
              </div>
              <div>
                LIVE_TRADING:{" "}
                <span
                  style={{
                    fontFamily: C.mono,
                    color: envState?.live_trading_disabled ? C.down : C.up,
                  }}
                >
                  {envState?.live_trading_disabled ? "DISABLED" : "ENABLED"}
                </span>
              </div>
            </div>

            {/* Force-reset button */}
            <button
              onClick={() => setShowResetConfirm(true)}
              disabled={loading || currentLevel === 0 || adminAuthed === false || !strategyId}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg cursor-pointer"
              style={{
                background:
                  currentLevel === 0 || adminAuthed === false || !strategyId ? C.bg3 : `${C.up}15`,
                border: `1px solid ${
                  currentLevel === 0 || adminAuthed === false || !strategyId
                    ? C.border
                    : `${C.up}50`
                }`,
                fontSize: 12,
                color:
                  currentLevel === 0 || adminAuthed === false || !strategyId ? C.text4 : C.up,
                fontWeight: 500,
                cursor:
                  currentLevel === 0 || adminAuthed === false || !strategyId
                    ? "not-allowed"
                    : "pointer",
              }}
              title={
                !strategyId
                  ? "PAPER_STRATEGY_ID 未配置, 无法 force-reset"
                  : currentLevel === 0
                    ? "当前 NORMAL, 无需 reset"
                    : adminAuthed === false
                    ? "需先设置 Admin Token (走 Execution 页面 ⚙ 入口)"
                    : "回归 L0 NORMAL (需要理由 + 高风险确认)"
              }
            >
              <RefreshCw size={13} />
              {adminAuthed === false ? "未授权 (需 Admin Token)" : "强制回归 L0 NORMAL"}
            </button>

            {/* L4 STAGED notice + Recovery flow (iter 137 W2-F F2) */}
            {needsManualApprove && (
              <div
                className="px-3 py-2 rounded space-y-2"
                style={{
                  background: `${C.warn}15`,
                  border: `1px solid ${C.warn}40`,
                  fontSize: 11,
                  color: C.warn,
                }}
              >
                <div className="flex items-center gap-1.5">
                  <AlertCircle size={12} />
                  <span style={{ fontWeight: 600 }}>L4 STAGED — 需人工审批恢复</span>
                </div>
                <div style={{ color: C.text3 }}>
                  L4_LIQUIDATE 状态触发. 恢复流程: 操作员请求 → admin 审批 (反向决策权).
                </div>

                {/* Step 1: Request recovery — when no pending approval */}
                {!pendingApprovalId && (
                  <button
                    onClick={() => setShowRequestRecovery(true)}
                    disabled={adminAuthed === false || currentLevel !== 4 || !strategyId}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg cursor-pointer"
                    style={{
                      background:
                        adminAuthed === false || currentLevel !== 4 || !strategyId ? C.bg3 : `${C.info}20`,
                      border: `1px solid ${
                        adminAuthed === false || currentLevel !== 4 || !strategyId
                          ? C.border
                          : `${C.info}50`
                      }`,
                      fontSize: 11,
                      color:
                        adminAuthed === false || currentLevel !== 4 || !strategyId ? C.text4 : C.info,
                      fontWeight: 500,
                      cursor:
                        adminAuthed === false || currentLevel !== 4 || !strategyId
                          ? "not-allowed"
                          : "pointer",
                    }}
                    title={
                      adminAuthed === false
                        ? "需先设置 Admin Token"
                        : currentLevel !== 4
                          ? "仅 L4_LIQUIDATE 可发起恢复"
                          : !strategyId
                            ? "PAPER_STRATEGY_ID 未配置, 无法发起请求"
                            : "发起 L4 恢复请求 (需 reviewer_note)"
                    }
                  >
                    <ShieldCheck size={13} />
                    发起 L4 恢复请求
                  </button>
                )}

                {/* Step 2: Pending approval — show approval_id + approve/reject buttons */}
                {pendingApprovalId && (
                  <>
                    <div
                      className="px-2 py-1.5 rounded"
                      style={{
                        background: C.bg3,
                        border: `1px solid ${C.border}`,
                        fontSize: 10,
                        color: C.text3,
                        fontFamily: C.mono,
                      }}
                    >
                      <div style={{ color: C.text4 }}>待审批 approval_id:</div>
                      <div style={{ color: C.text2, wordBreak: "break-all" }}>{pendingApprovalId}</div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        onClick={() => setShowApproveRecovery("approve")}
                        disabled={adminAuthed === false}
                        className="flex items-center justify-center gap-1 px-2 py-1.5 rounded cursor-pointer"
                        style={{
                          background: adminAuthed === false ? C.bg3 : `${C.down}20`,
                          border: `1px solid ${adminAuthed === false ? C.border : `${C.down}50`}`,
                          fontSize: 11,
                          color: adminAuthed === false ? C.text4 : C.down,
                          fontWeight: 500,
                          cursor: adminAuthed === false ? "not-allowed" : "pointer",
                        }}
                      >
                        <ShieldCheck size={12} />
                        批准
                      </button>
                      <button
                        onClick={() => setShowApproveRecovery("reject")}
                        disabled={adminAuthed === false}
                        className="flex items-center justify-center gap-1 px-2 py-1.5 rounded cursor-pointer"
                        style={{
                          background: adminAuthed === false ? C.bg3 : `${C.up}20`,
                          border: `1px solid ${adminAuthed === false ? C.border : `${C.up}50`}`,
                          fontSize: 11,
                          color: adminAuthed === false ? C.text4 : C.up,
                          fontWeight: 500,
                          cursor: adminAuthed === false ? "not-allowed" : "pointer",
                        }}
                      >
                        <ShieldX size={12} />
                        拒绝
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* CRIT ops disclosure */}
            <div
              className="px-3 py-2 rounded"
              style={{
                background: C.bg2,
                border: `1px dashed ${C.border}`,
                fontSize: 10,
                color: C.text4,
                lineHeight: 1.5,
              }}
            >
              <div className="flex items-center gap-1 mb-1" style={{ color: C.text3 }}>
                <Zap size={10} />
                <span style={{ fontWeight: 600 }}>CRIT ops (CC-only)</span>
              </div>
              <div>env_flip · execute_phase · emergency_close_all · pause_trading 仍只能通过 CC bash 触发, UI 不直接暴露</div>
            </div>
          </div>
        </Card>
      </div>

      {/* Force-reset confirm modal */}
      {showResetConfirm && (
        <ConfirmModal
          title="强制回归 L0 NORMAL"
          message={`当前 L${currentLevel} ${levelDef.name}. Force-reset 会绕过 recovery streak 直接归零熔断状态. 请输入理由后确认.`}
          safetyTier="HIGH"
          requiredReason
          reasonMinLength={5}
          onConfirm={handleForceReset}
          onCancel={() => setShowResetConfirm(false)}
        />
      )}

      {/* iter 137 W2-F F2 — L4 recovery request modal (HIGH tier, reviewer_note required) */}
      {showRequestRecovery && (
        <ConfirmModal
          title="发起 L4 恢复请求"
          message="当前 L4_LIQUIDATE. 发起恢复请求会创建 approval_queue 待审批记录, 需 admin 审批后才生效. 请填写恢复理由 (≥5 字符)."
          safetyTier="HIGH"
          requiredReason
          reasonMinLength={5}
          onConfirm={handleRequestRecovery}
          onCancel={() => setShowRequestRecovery(false)}
        />
      )}

      {/* iter 137 W2-F F2 — L4 approve/reject modal (HIGH/CRIT tier, reverse-decision-权) */}
      {showApproveRecovery && (
        <ConfirmModal
          title={showApproveRecovery === "approve" ? "批准 L4 恢复" : "拒绝 L4 恢复"}
          message={
            showApproveRecovery === "approve"
              ? `审批 approval_id=${pendingApprovalId?.slice(0, 8)}… 批准后 strategy 状态将从 L4_LIQUIDATE 恢复. 请填写批准理由 (审计留痕).`
              : `审批 approval_id=${pendingApprovalId?.slice(0, 8)}… 拒绝后 strategy 保持 L4_LIQUIDATE 状态. 请填写拒绝理由 (审计留痕).`
          }
          safetyTier={showApproveRecovery === "approve" ? "CRIT" : "HIGH"}
          requiredReason
          reasonMinLength={5}
          requiredPhrase={showApproveRecovery === "approve" ? "APPROVE-L4-RECOVERY" : undefined}
          cooldownSeconds={showApproveRecovery === "approve" ? 5 : 0}
          onConfirm={handleApproveRecovery}
          onCancel={() => setShowApproveRecovery(null)}
        />
      )}
    </div>
  );
}
