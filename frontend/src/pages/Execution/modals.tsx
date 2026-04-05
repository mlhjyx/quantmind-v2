/**
 * Execution modals — AdminTokenModal, ConfirmModal, DriftPreviewModal.
 * Extracted from Execution.tsx for maintainability.
 */
import { useState } from "react";
import { C } from "@/theme";
import type { DriftFixPreview } from "@/api/execution";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function fmtMoney(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return v.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

// ---------------------------------------------------------------------------
// Admin Token Modal
// ---------------------------------------------------------------------------

export function AdminTokenModal({ onSubmit, onCancel }: { onSubmit: (t: string) => void; onCancel: () => void }) {
  const [val, setVal] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="rounded-xl p-6" style={{ background: C.bg2, border: `1px solid ${C.border}`, width: 360 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text1, marginBottom: 12 }}>输入Admin Token</div>
        <input
          type="password"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder="ADMIN_TOKEN"
          className="w-full rounded-lg px-3 py-2 mb-4"
          style={{ background: C.bg3, border: `1px solid ${C.border}`, color: C.text1, fontSize: 13, outline: "none" }}
          onKeyDown={(e) => e.key === "Enter" && val && onSubmit(val)}
        />
        <div className="flex gap-2 justify-end">
          <button onClick={onCancel} className="px-4 py-1.5 rounded-lg cursor-pointer" style={{ fontSize: 12, background: C.bg3, color: C.text3 }}>取消</button>
          <button onClick={() => val && onSubmit(val)} className="px-4 py-1.5 rounded-lg cursor-pointer" style={{ fontSize: 12, background: C.accent, color: "#fff" }}>确定</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confirm Modal
// ---------------------------------------------------------------------------

export function ConfirmModal({
  title,
  message,
  danger,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [input, setInput] = useState("");
  const needConfirmText = danger;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="rounded-xl p-6" style={{ background: C.bg2, border: `1px solid ${danger ? C.up : C.border}`, width: 400 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: danger ? C.up : C.text1, marginBottom: 8 }}>{title}</div>
        <div style={{ fontSize: 12, color: C.text3, marginBottom: 16, lineHeight: 1.6 }}>{message}</div>
        {needConfirmText && (
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder='输入 CONFIRM 确认'
            className="w-full rounded-lg px-3 py-2 mb-4"
            style={{ background: C.bg3, border: `1px solid ${C.up}40`, color: C.text1, fontSize: 13, outline: "none" }}
          />
        )}
        <div className="flex gap-2 justify-end">
          <button onClick={onCancel} className="px-4 py-1.5 rounded-lg cursor-pointer" style={{ fontSize: 12, background: C.bg3, color: C.text3 }}>取消</button>
          <button
            onClick={onConfirm}
            disabled={needConfirmText && input !== "CONFIRM"}
            className="px-4 py-1.5 rounded-lg cursor-pointer"
            style={{
              fontSize: 12,
              background: needConfirmText && input !== "CONFIRM" ? C.bg3 : (danger ? C.up : C.accent),
              color: needConfirmText && input !== "CONFIRM" ? C.text4 : "#fff",
            }}
          >
            确定
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drift Fix Preview Modal
// ---------------------------------------------------------------------------

export function DriftPreviewModal({
  preview,
  onExecute,
  onCancel,
}: {
  preview: DriftFixPreview;
  onExecute: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="rounded-xl p-6 overflow-y-auto" style={{ background: C.bg2, border: `1px solid ${C.border}`, width: 520, maxHeight: "80vh" }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text1, marginBottom: 12 }}>偏差修复预览</div>

        {preview.sell_plan.length > 0 && (
          <>
            <div style={{ fontSize: 11, color: C.down, fontWeight: 600, marginBottom: 6 }}>卖出计划 (释放 {fmtMoney(preview.sell_total_release)})</div>
            <table className="w-full mb-4" style={{ fontSize: 11 }}>
              <thead><tr style={{ color: C.text4 }}>
                <th className="text-left py-1 font-normal">代码</th>
                <th className="text-left py-1 font-normal">名称</th>
                <th className="text-right py-1 font-normal">数量</th>
                <th className="text-right py-1 font-normal">金额</th>
                <th className="text-left py-1 font-normal pl-3">原因</th>
              </tr></thead>
              <tbody>
                {preview.sell_plan.map((s) => (
                  <tr key={s.code} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td className="py-1" style={{ fontFamily: "monospace", color: C.text2 }}>{s.code}</td>
                    <td className="py-1" style={{ color: C.text2 }}>{s.name}</td>
                    <td className="py-1 text-right" style={{ fontFamily: "monospace", color: C.down }}>{s.volume}</td>
                    <td className="py-1 text-right" style={{ fontFamily: "monospace", color: C.text2 }}>{fmtMoney(s.estimated_amount)}</td>
                    <td className="py-1 pl-3" style={{ color: C.text4 }}>{s.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {preview.buy_plan.length > 0 && (
          <>
            <div style={{ fontSize: 11, color: C.up, fontWeight: 600, marginBottom: 6 }}>买入计划 (需要 {fmtMoney(preview.buy_total_need)})</div>
            <table className="w-full mb-4" style={{ fontSize: 11 }}>
              <thead><tr style={{ color: C.text4 }}>
                <th className="text-left py-1 font-normal">代码</th>
                <th className="text-left py-1 font-normal">名称</th>
                <th className="text-right py-1 font-normal">目标金额</th>
                <th className="text-left py-1 font-normal pl-3">原因</th>
              </tr></thead>
              <tbody>
                {preview.buy_plan.map((b) => (
                  <tr key={b.code} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td className="py-1" style={{ fontFamily: "monospace", color: C.text2 }}>{b.code}</td>
                    <td className="py-1" style={{ color: C.text2 }}>{b.name}</td>
                    <td className="py-1 text-right" style={{ fontFamily: "monospace", color: C.up }}>{fmtMoney(b.target_value)}</td>
                    <td className="py-1 pl-3" style={{ color: C.text4 }}>{b.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        <div className="rounded-lg p-3 mb-4" style={{ background: C.bg3, fontSize: 11, color: C.text3 }}>
          <div>可用现金: {fmtMoney(preview.funding.total_available_after_sell)} (卖出释放 {fmtMoney(preview.funding.overbought_release)})</div>
          <div>缺失需要: {fmtMoney(preview.funding.missing_need)} ({preview.funding.missing_count}只，可买{preview.funding.can_buy_count}只)</div>
          {preview.funding.funding_gap > 0 && (
            <div style={{ color: C.warn }}>资金缺口: {fmtMoney(preview.funding.funding_gap)}</div>
          )}
        </div>

        <div className="flex gap-2 justify-end">
          <button onClick={onCancel} className="px-4 py-1.5 rounded-lg cursor-pointer" style={{ fontSize: 12, background: C.bg3, color: C.text3 }}>取消</button>
          <button onClick={onExecute} className="px-4 py-1.5 rounded-lg cursor-pointer" style={{ fontSize: 12, background: C.accent, color: "#fff" }}>
            执行修复
          </button>
        </div>
      </div>
    </div>
  );
}
