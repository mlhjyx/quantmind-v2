import { useNotifications, type Toast as ToastType, type NotificationLevel } from "@/contexts/NotificationContext";
import { useNavigate } from "react-router-dom";

const LEVEL_COLORS: Record<NotificationLevel, string> = {
  P0: "border-l-red-500",
  P1: "border-l-yellow-400",
  P2: "border-l-blue-400",
  P3: "border-l-green-400",
};

const LEVEL_ICONS: Record<NotificationLevel, string> = {
  P0: "🔴",
  P1: "🟡",
  P2: "🔵",
  P3: "✅",
};

function ToastItem({ toast }: { toast: ToastType }) {
  const { dismissToast } = useNotifications();
  const navigate = useNavigate();

  function handleClick() {
    if (toast.link) {
      navigate(toast.link);
      dismissToast(toast.id);
    }
  }

  return (
    <div
      className={[
        "relative flex items-start gap-3 w-80 rounded-xl border border-white/10",
        "bg-slate-900/90 backdrop-blur-xl shadow-2xl",
        "border-l-4 pl-3 pr-4 py-3",
        "animate-slide-in",
        LEVEL_COLORS[toast.level],
        toast.link ? "cursor-pointer" : "",
      ].join(" ")}
      onClick={toast.link ? handleClick : undefined}
    >
      <span className="text-base mt-0.5 shrink-0">{LEVEL_ICONS[toast.level]}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-100 leading-tight">{toast.title}</p>
        {toast.content && (
          <p className="text-xs text-slate-400 mt-0.5 leading-snug line-clamp-2">
            {toast.content}
          </p>
        )}
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          dismissToast(toast.id);
        }}
        className="shrink-0 text-slate-500 hover:text-slate-300 transition-colors text-sm leading-none mt-0.5"
        aria-label="关闭"
      >
        ✕
      </button>
    </div>
  );
}

export function ToastContainer() {
  const { toasts } = useNotifications();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} />
      ))}
    </div>
  );
}
