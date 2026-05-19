/**
 * AdminTokenModal — global admin token entry for privileged ops.
 *
 * Frontend Design v3 §2.4 — Promoted from Execution/modals.tsx for global reuse.
 *
 * 配合 SafetyControlPanel + Execution + future ops requiring ADMIN_TOKEN gate.
 * TODO Phase I §3.4: move token from localStorage → httpOnly cookie (audit P0-22).
 */

import { useEffect, useRef, useState } from "react";
import { KeyRound } from "lucide-react";
import { C } from "@/theme";

interface AdminTokenModalProps {
  onSubmit: (token: string) => void;
  onCancel: () => void;
  title?: string;
}

export function AdminTokenModal({ onSubmit, onCancel, title }: AdminTokenModalProps) {
  const [val, setVal] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // P2 fix (typescript-reviewer Session 57+1 round-2): ESC-to-close + focus trap
  // + ARIA. 旧 pattern 无 ESC + 无 focus trap + 缺 role/aria — keyboard-only user
  // 无法 cancel. 高风险 token 入口 UX 反误操作必备.
  useEffect(() => {
    inputRef.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.6)" }}
      // 显式 backdrop click → cancel (UX 一致性)
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-token-modal-title"
    >
      <div
        className="rounded-xl p-6"
        style={{ background: C.bg2, border: `1px solid ${C.border}`, width: 360 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-3">
          <KeyRound size={14} color={C.accent} />
          <div id="admin-token-modal-title" style={{ fontSize: 14, fontWeight: 700, color: C.text1 }}>
            {title ?? "输入 Admin Token"}
          </div>
        </div>
        <input
          ref={inputRef}
          type="password"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder="ADMIN_TOKEN"
          className="w-full rounded-lg px-3 py-2 mb-4"
          style={{
            background: C.bg3,
            border: `1px solid ${C.border}`,
            color: C.text1,
            fontSize: 13,
            outline: "none",
            fontFamily: C.mono,
          }}
          onKeyDown={(e) => e.key === "Enter" && val && onSubmit(val)}
        />
        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-1.5 rounded-lg cursor-pointer"
            style={{ fontSize: 12, background: C.bg3, color: C.text3 }}
          >
            取消
          </button>
          <button
            onClick={() => val && onSubmit(val)}
            disabled={!val}
            className="px-4 py-1.5 rounded-lg cursor-pointer"
            style={{
              fontSize: 12,
              background: val ? C.accent : C.bg3,
              color: val ? "#fff" : C.text4,
              cursor: val ? "pointer" : "not-allowed",
            }}
          >
            确定
          </button>
        </div>
      </div>
    </div>
  );
}
