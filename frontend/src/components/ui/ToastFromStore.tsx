/**
 * ToastFromStore — Zustand notificationStore toast renderer (A3 partial close).
 *
 * Frontend Design v3 §4.2 (ISSUES_PENDING_REGISTRY §4 A3): 4 notification systems
 * had 3 unrendered. Zustand `useNotificationStore` is real production source (axios
 * interceptor at client.ts:31 calls add() on 401/403/422/429/503/500 errors), but
 * had NO UI subscriber → silent fail (errors logged to store, never visible to user).
 *
 * This component subscribes to the Zustand store and renders toasts at top-right
 * corner (stack of up to 4, color-coded by type, auto-dismiss per store TTL).
 *
 * Distinct from `Toast.tsx` (React Context-based, NotificationContext.toasts):
 *   - Toast.tsx: P0/P1/P2/P3 levels, mock-seeded, drawer bell + corner toast
 *   - ToastFromStore.tsx (本): info/success/warning/error types, axios-driven, corner only
 *
 * Per notificationStore.ts docstring: full consolidation 4→1 systems is ~4-6h refactor.
 * 本 partial close ensures axios errors ARE visible (反 silent fail at boundary,
 * 铁律 33), without the full Context/Zustand merge.
 *
 * Mount in main.tsx alongside existing ToastContainer (parallel render, distinct
 * position offset to avoid overlap).
 */

import { useNotificationStore, type NotificationType } from "@/store/notificationStore";

const TYPE_COLORS: Record<NotificationType, { border: string; bg: string; text: string; icon: string }> = {
  info:    { border: "border-blue-500/40",    bg: "bg-blue-900/30",    text: "text-blue-200",    icon: "ℹ️" },
  success: { border: "border-emerald-500/40", bg: "bg-emerald-900/30", text: "text-emerald-200", icon: "✅" },
  warning: { border: "border-amber-500/40",   bg: "bg-amber-900/30",   text: "text-amber-200",   icon: "⚠️" },
  error:   { border: "border-red-500/40",     bg: "bg-red-900/30",     text: "text-red-200",     icon: "❌" },
};

export function ToastFromStore() {
  const notifications = useNotificationStore((s) => s.notifications);
  const remove = useNotificationStore((s) => s.remove);

  if (notifications.length === 0) return null;

  // Render up to 4 most recent — old toasts auto-removed by store TTL (default 5s).
  const visible = notifications.slice(-4);

  return (
    <div
      className="fixed top-20 right-4 z-50 flex flex-col gap-2"
      // Offset below existing ToastContainer (top-4) to avoid visual overlap (4 → 80px).
    >
      {visible.map((n) => {
        const c = TYPE_COLORS[n.type];
        return (
          <div
            key={n.id}
            className={[
              "relative flex items-start gap-3 w-80 rounded-xl border border-white/10 px-4 py-3",
              "backdrop-blur-xl shadow-2xl border-l-4",
              c.bg,
              c.border,
              "animate-slide-in",
            ].join(" ")}
            role="alert"
          >
            <span className="text-base mt-0.5 shrink-0">{c.icon}</span>
            <div className="flex-1 min-w-0">
              <p className={`text-sm font-medium leading-tight ${c.text}`}>{n.title}</p>
              {n.message && (
                <p className="text-xs text-slate-400 mt-0.5 leading-snug line-clamp-2">
                  {n.message}
                </p>
              )}
            </div>
            <button
              onClick={() => remove(n.id)}
              className="shrink-0 text-slate-500 hover:text-slate-300 transition-colors text-sm leading-none mt-0.5"
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
