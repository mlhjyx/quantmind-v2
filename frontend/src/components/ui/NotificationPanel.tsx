import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useNotifications,
  type Notification,
  type NotificationLevel,
} from "@/contexts/NotificationContext";

const LEVEL_DOT: Record<NotificationLevel, string> = {
  P0: "bg-red-500",
  P1: "bg-yellow-400",
  P2: "bg-blue-400",
  P3: "bg-green-400",
};

const LEVEL_ACCENT: Record<NotificationLevel, string> = {
  P0: "border-l-red-500",
  P1: "border-l-yellow-400",
  P2: "border-l-blue-400",
  P3: "border-l-green-400",
};

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "今天";
  if (d.toDateString() === yesterday.toDateString()) return "昨天";
  return d.toISOString().slice(0, 10);
}

function groupByDay(notifications: Notification[]): { label: string; items: Notification[] }[] {
  const map = new Map<string, Notification[]>();
  for (const n of notifications) {
    const label = dayLabel(n.created_at);
    const existing = map.get(label);
    if (existing) {
      existing.push(n);
    } else {
      map.set(label, [n]);
    }
  }
  return Array.from(map.entries()).map(([label, items]) => ({ label, items }));
}

function NotificationItem({ n }: { n: Notification }) {
  const { markRead } = useNotifications();
  const navigate = useNavigate();

  function handleClick() {
    markRead(n.id);
    if (n.link) navigate(n.link);
  }

  return (
    <div
      onClick={handleClick}
      className={[
        "flex gap-3 px-3 py-2.5 transition-colors",
        n.link ? "cursor-pointer" : "",
        n.is_read
          ? "hover:bg-white/3"
          : `border-l-2 pl-2 ${LEVEL_ACCENT[n.level]} hover:bg-white/5 bg-white/4`,
      ].join(" ")}
    >
      <div className="shrink-0 mt-1">
        <span className={`inline-block w-2 h-2 rounded-full ${LEVEL_DOT[n.level]} ${n.is_read ? "opacity-30" : ""}`} />
      </div>
      <div className="flex-1 min-w-0">
        <p className={`text-[13px] leading-snug ${n.is_read ? "text-slate-400" : "text-slate-100 font-medium"}`}>
          {n.title}
        </p>
        {n.content && (
          <p className="text-[12px] text-slate-500 mt-0.5 leading-snug line-clamp-2">
            {n.content}
          </p>
        )}
        <p className="text-[11px] text-slate-600 mt-1">{relativeTime(n.created_at)}</p>
      </div>
    </div>
  );
}

export function NotificationPanel() {
  const { notifications, unreadCount, markAllRead } = useNotifications();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [open]);

  const groups = groupByDay(notifications);

  return (
    <div ref={containerRef} className="relative">
      {/* Bell button */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex items-center justify-center w-8 h-8 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors"
        title="通知中心"
        aria-label="通知中心"
      >
        <span className="text-base">🔔</span>
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-0.5 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center leading-none">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute right-0 top-10 w-[380px] max-h-[70vh] flex flex-col rounded-xl border border-white/10 bg-slate-900/90 backdrop-blur-xl shadow-2xl z-50 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/8 shrink-0">
            <span className="text-sm font-semibold text-slate-200">通知中心</span>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
              >
                全部已读
              </button>
            )}
          </div>

          {/* Notification list */}
          <div className="overflow-y-auto flex-1">
            {notifications.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-slate-500 text-sm">
                暂无通知
              </div>
            ) : (
              groups.map((group) => (
                <div key={group.label}>
                  <p className="px-3 py-1.5 text-[11px] text-slate-500 uppercase tracking-wider bg-white/3 border-b border-white/5">
                    {group.label}
                  </p>
                  {group.items.map((n) => (
                    <NotificationItem key={n.id} n={n} />
                  ))}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
