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

import { useCallback, useEffect, useState } from "react";
import { Shield, AlertCircle, Zap, RefreshCw, History } from "lucide-react";
import { C } from "@/theme";
import { Card, CardHeader } from "@/components/shared";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import apiClient from "@/api/client";
import type { CircuitBreakerState } from "@/types/dashboard";
import { fetchCircuitBreakerState } from "@/api/dashboard";
import { fetchEnvState, type EnvState } from "@/api/system";
import { isAdminAuthed } from "@/api/execution";

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
  const [state, setState] = useState<CircuitBreakerState | null>(null);
  const [envState, setEnvState] = useState<EnvState | null>(null);
  const [loading, setLoading] = useState(true);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [actionMsg, setActionMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // P2 fix (security-reviewer Session 57+1 round-4): pre-check admin auth state.
  // 旧 pattern user fill reason → click confirm → 401 silent error. 现 pre-check →
  // button disabled with tooltip "需先设置 admin token", UX 阻挡反误操作.
  const [adminAuthed, setAdminAuthed] = useState<boolean | null>(null);

  // P2 fix (typescript-reviewer Session 57+1 round-4): useCallback wrap on load
  // (沿用 SystemSettings 体例). 当前未消费 ref equality, 但 future maintainer 加
  // prop dep 时 useCallback boundary prevents silent stale-closure regression.
  const load = useCallback(async () => {
    setLoading(true);
    const [cb, env, authed] = await Promise.all([
      fetchCircuitBreakerState().catch(() => null),
      fetchEnvState().catch(() => null),
      isAdminAuthed().catch(() => false),
    ]);
    setState(cb);
    setEnvState(env);
    setAdminAuthed(authed);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 10_000);
    return () => clearInterval(id);
  }, [load]);

  const handleForceReset = async (meta: { reason?: string }) => {
    setShowResetConfirm(false);
    try {
      await apiClient.post("/risk/force-reset/default", {
        reason: meta.reason ?? "manual reset via frontend SafetyControlPanel",
      });
      setActionMsg({ ok: true, text: "Force-reset 成功, 刷新中..." });
      void load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "请求失败";
      setActionMsg({ ok: false, text: `Force-reset 失败: ${msg}` });
    }
    setTimeout(() => setActionMsg(null), 5000);
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
              disabled={loading || currentLevel === 0 || adminAuthed === false}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg cursor-pointer"
              style={{
                background: currentLevel === 0 || adminAuthed === false ? C.bg3 : `${C.up}15`,
                border: `1px solid ${currentLevel === 0 || adminAuthed === false ? C.border : `${C.up}50`}`,
                fontSize: 12,
                color: currentLevel === 0 || adminAuthed === false ? C.text4 : C.up,
                fontWeight: 500,
                cursor: currentLevel === 0 || adminAuthed === false ? "not-allowed" : "pointer",
              }}
              title={
                currentLevel === 0
                  ? "当前 NORMAL, 无需 reset"
                  : adminAuthed === false
                    ? "需先设置 Admin Token (走 Execution 页面 ⚙ 入口)"
                    : "回归 L0 NORMAL (需要理由 + 高风险确认)"
              }
            >
              <RefreshCw size={13} />
              {adminAuthed === false ? "未授权 (需 Admin Token)" : "强制回归 L0 NORMAL"}
            </button>

            {/* L4 STAGED notice */}
            {needsManualApprove && (
              <div
                className="px-3 py-2 rounded"
                style={{
                  background: `${C.warn}15`,
                  border: `1px solid ${C.warn}40`,
                  fontSize: 11,
                  color: C.warn,
                }}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <AlertCircle size={12} />
                  <span style={{ fontWeight: 600 }}>需要人工 approve</span>
                </div>
                <div style={{ color: C.text3 }}>
                  L4 STAGED 流程: 当前需要 admin token + 反向决策权确认 (CC ops only)
                </div>
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
    </div>
  );
}
