/**
 * ConfirmModal — global safety-tiered confirmation dialog.
 *
 * Frontend Design v3 §2.4 — Promoted from Execution/modals.tsx for global reuse.
 *
 * 4 safety tiers (per V3_AUDIT_S9_UX_CONTROL_PLANE.md §44):
 *   LOW  — simple yes/no (e.g. cancel single order)
 *   MED  — reason required (>= 5 chars, e.g. factor archive)
 *   HIGH — reason + danger highlight + CONFIRM phrase (e.g. emergency_close)
 *   CRIT — typed phrase + env match check + cooldown timer (e.g. env_flip / execute_phase)
 *
 * 集成现状: Execution/index.tsx 黄金模板 = HIGH tier. SafetyControlPanel = CRIT tier.
 */

import { useState, useEffect } from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { C } from "@/theme";

export type SafetyTier = "LOW" | "MED" | "HIGH" | "CRIT";

interface ConfirmModalProps {
  title: string;
  message: string;
  safetyTier?: SafetyTier;
  // CRIT-specific
  requiredPhrase?: string; // e.g. "EXECUTE-PAPER-20260519"
  envCheckRequired?: "paper" | "live"; // 必须当前 mode 匹配
  currentEnvMode?: "paper" | "live"; // 来自 envState
  cooldownSeconds?: number; // 默认 5s
  // MED/HIGH-specific
  requiredReason?: boolean;
  reasonMinLength?: number; // 默认 5
  // 兼容旧 Execution/modals.tsx danger boolean
  danger?: boolean;
  onConfirm: (meta: { reason?: string; phrase?: string }) => void | Promise<void>;
  onCancel: () => void;
}

export function ConfirmModal({
  title,
  message,
  safetyTier,
  requiredPhrase,
  envCheckRequired,
  currentEnvMode,
  cooldownSeconds,
  requiredReason,
  reasonMinLength = 5,
  danger,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  // 兼容旧 danger boolean → HIGH tier
  const tier: SafetyTier = safetyTier ?? (danger ? "HIGH" : "LOW");
  const [phrase, setPhrase] = useState("");
  const [reason, setReason] = useState("");
  const [legacyConfirm, setLegacyConfirm] = useState("");
  const [cooldown, setCooldown] = useState(tier === "CRIT" ? cooldownSeconds ?? 5 : 0);

  useEffect(() => {
    if (tier !== "CRIT" || cooldown <= 0) return;
    const id = setInterval(() => {
      setCooldown((c) => (c > 0 ? c - 1 : 0));
    }, 1000);
    return () => clearInterval(id);
  }, [tier, cooldown]);

  const dangerTier = tier === "HIGH" || tier === "CRIT";
  const titleColor = dangerTier ? C.up : C.text1;
  const borderColor = dangerTier ? `${C.up}50` : C.border;

  // 校验
  const envOk = !envCheckRequired || envCheckRequired === currentEnvMode;
  const phraseOk = !requiredPhrase || phrase === requiredPhrase;
  // 兼容旧 danger 模式 (无 requiredPhrase 但有 danger) → 仍然要求 CONFIRM
  const legacyConfirmRequired = danger && !requiredPhrase && tier === "HIGH" && !requiredReason;
  const legacyConfirmOk = !legacyConfirmRequired || legacyConfirm === "CONFIRM";
  const reasonOk =
    !requiredReason || (reason.trim().length >= reasonMinLength);
  const cooldownOk = tier !== "CRIT" || cooldown === 0;
  const allOk = envOk && phraseOk && legacyConfirmOk && reasonOk && cooldownOk;

  const tierBadgeText = tier === "CRIT" ? "极高风险" : tier === "HIGH" ? "高风险" : tier === "MED" ? "需理由" : "确认";
  const tierBadgeColor =
    tier === "CRIT" ? C.up : tier === "HIGH" ? C.warn : tier === "MED" ? C.info : C.text3;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.6)" }}
    >
      <div
        className="rounded-xl p-6"
        style={{ background: C.bg2, border: `1px solid ${borderColor}`, width: 420 }}
      >
        <div className="flex items-center gap-2 mb-2">
          {dangerTier ? (
            <ShieldAlert size={16} color={C.up} />
          ) : (
            <AlertTriangle size={14} color={C.text3} />
          )}
          <div style={{ fontSize: 14, fontWeight: 700, color: titleColor }}>{title}</div>
          <span
            className="ml-auto px-2 py-0.5 rounded"
            style={{ fontSize: 10, color: tierBadgeColor, background: `${tierBadgeColor}15` }}
          >
            {tierBadgeText}
          </span>
        </div>
        <div style={{ fontSize: 12, color: C.text3, marginBottom: 16, lineHeight: 1.6 }}>
          {message}
        </div>

        {/* CRIT: env mismatch warning */}
        {envCheckRequired && !envOk && (
          <div
            className="px-3 py-2 rounded mb-3"
            style={{ background: `${C.up}10`, border: `1px solid ${C.up}40`, fontSize: 11, color: C.up }}
          >
            ⚠ 当前 ENV={currentEnvMode}, 操作要求 ENV={envCheckRequired}. 请先切换.
          </div>
        )}

        {/* CRIT phrase input */}
        {requiredPhrase && (
          <>
            <div style={{ fontSize: 11, color: C.text3, marginBottom: 4 }}>
              输入确认短语:{" "}
              <span style={{ fontFamily: C.mono, color: C.up }}>{requiredPhrase}</span>
            </div>
            <input
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              placeholder={requiredPhrase}
              className="w-full rounded-lg px-3 py-2 mb-3"
              style={{
                background: C.bg3,
                border: `1px solid ${phraseOk ? C.up : C.border}40`,
                color: C.text1,
                fontSize: 13,
                outline: "none",
                fontFamily: C.mono,
              }}
            />
          </>
        )}

        {/* HIGH/MED reason input */}
        {requiredReason && (
          <>
            <div style={{ fontSize: 11, color: C.text3, marginBottom: 4 }}>
              理由 (≥ {reasonMinLength} 字符):
            </div>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="说明操作原因, 留 audit trail..."
              rows={2}
              className="w-full rounded-lg px-3 py-2 mb-3"
              style={{
                background: C.bg3,
                border: `1px solid ${C.border}`,
                color: C.text1,
                fontSize: 12,
                outline: "none",
                resize: "vertical",
              }}
            />
          </>
        )}

        {/* Legacy CONFIRM input (Execution backward-compat) */}
        {legacyConfirmRequired && (
          <input
            value={legacyConfirm}
            onChange={(e) => setLegacyConfirm(e.target.value)}
            placeholder="输入 CONFIRM 确认"
            className="w-full rounded-lg px-3 py-2 mb-4"
            style={{
              background: C.bg3,
              border: `1px solid ${C.up}40`,
              color: C.text1,
              fontSize: 13,
              outline: "none",
            }}
          />
        )}

        {/* CRIT cooldown */}
        {tier === "CRIT" && cooldown > 0 && (
          <div style={{ fontSize: 11, color: C.warn, marginBottom: 12 }}>
            冷却中 {cooldown}s ... (防误触)
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-1.5 rounded-lg cursor-pointer"
            style={{ fontSize: 12, background: C.bg3, color: C.text3 }}
          >
            取消
          </button>
          <button
            onClick={() => allOk && void onConfirm({ reason: reason || undefined, phrase: phrase || undefined })}
            disabled={!allOk}
            className="px-4 py-1.5 rounded-lg cursor-pointer"
            style={{
              fontSize: 12,
              background: !allOk ? C.bg3 : dangerTier ? C.up : C.accent,
              color: !allOk ? C.text4 : "#fff",
              cursor: !allOk ? "not-allowed" : "pointer",
            }}
          >
            确定
          </button>
        </div>
      </div>
    </div>
  );
}
