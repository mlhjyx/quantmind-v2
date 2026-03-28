/**
 * NotificationSystem — 铃铛图标 + 通知中心 Dropdown
 *
 * 消费 contexts/NotificationContext (Provider + Toast已在Layout中注册)
 * WebSocket: 监听 /ws/socket.io notification / risk_alert / pt_status 事件
 */
import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { io } from "socket.io-client";
import {
  useNotifications,
  type NotificationLevel,
} from "@/contexts/NotificationContext";

// ─────────────────────────────────────────────
// Priority label styling
// ─────────────────────────────────────────────
const LEVEL_STYLES: Record<NotificationLevel, { dot: string; label: string; badge: string }> = {
  P0: { dot: "bg-red-500", label: "text-red-400", badge: "bg-red-500" },
  P1: { dot: "bg-yellow-400", label: "text-yellow-400", badge: "bg-yellow-500" },
  P2: { dot: "bg-blue-400", label: "text-blue-400", badge: "bg-blue-500" },
  P3: { dot: "bg-green-400", label: "text-green-400", badge: "bg-green-500" },
};

function formatRelative(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins}分钟前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}小时前`;
  return `${Math.floor(hrs / 24)}天前`;
}

// ─────────────────────────────────────────────
// WebSocket hook — connects and feeds addNotification
// ─────────────────────────────────────────────
export function useNotifWebSocket() {
  const { addNotification } = useNotifications();

  useEffect(() => {
    let connected = false;
    const socket = io("/", {
      path: "/ws/socket.io",
      transports: ["websocket"],
      reconnectionAttempts: 3,
      timeout: 4000,
      autoConnect: true,
    });

    socket.on("connect", () => {
      connected = true;
    });

    socket.on("notification", (data: {
      level?: NotificationLevel;
      category?: string;
      title?: string;
      content?: string;
      link?: string;
    }) => {
      addNotification({
        level: data.level ?? "P2",
        category: data.category ?? "系统",
        title: data.title ?? "通知",
        content: data.content,
        link: data.link,
      });
    });

    socket.on("risk_alert", (data: { level?: number; message?: string }) => {
      addNotification({
        level: "P0",
        category: "风控",
        title: `风控告警 L${data.level ?? "?"}`,
        content: data.message ?? "风控熔断触发",
        link: "/settings/risk",
      });
    });

    socket.on("pt_status", (data: { message?: string; link?: string }) => {
      addNotification({
        level: "P2",
        category: "PT",
        title: "PT状态更新",
        content: data.message ?? "Paper Trading状态变更",
        link: data.link,
      });
    });

    return () => {
      void connected; // suppress unused warning
      socket.disconnect();
    };
  }, [addNotification]);
}

// ─────────────────────────────────────────────
// Notification center dropdown
// ─────────────────────────────────────────────
function NotificationDropdown({ onClose }: { onClose: () => void }) {
  const { notifications, unreadCount, markAllRead, markRead } = useNotifications();
  const navigate = useNavigate();

  function handleItemClick(id: string, link?: string) {
    markRead(id);
    if (link) {
      navigate(link);
      onClose();
    }
  }

  return (
    <div
      className="absolute right-0 top-full mt-2 w-80 rounded-2xl border border-white/10 bg-[rgba(10,14,35,0.97)] backdrop-blur-xl shadow-2xl z-50 overflow-hidden"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-200">通知中心</span>
          {unreadCount > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-red-500 text-white font-bold leading-none">
              {unreadCount}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {unreadCount > 0 && (
            <button
              onClick={markAllRead}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              全部已读
            </button>
          )}
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors text-sm"
          >
            ✕
          </button>
        </div>
      </div>

      {/* List */}
      <div className="max-h-96 overflow-y-auto">
        {notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <div className="text-3xl mb-2 opacity-50">🔔</div>
            <p className="text-sm">暂无通知</p>
          </div>
        ) : (
          <div className="divide-y divide-white/5">
            {notifications.map((n) => {
              const s = LEVEL_STYLES[n.level];
              return (
                <div
                  key={n.id}
                  onClick={() => handleItemClick(n.id, n.link)}
                  className={[
                    "px-4 py-3 transition-colors",
                    n.link ? "cursor-pointer hover:bg-white/5" : "hover:bg-white/3",
                    !n.is_read ? "bg-white/[0.03]" : "",
                  ].join(" ")}
                >
                  <div className="flex items-start gap-2.5">
                    <div
                      className={[
                        "w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0",
                        n.is_read ? "bg-white/15" : s.dot,
                      ].join(" ")}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className={`text-[10px] font-bold ${s.label}`}>
                          {n.level}
                        </span>
                        <span className="text-[10px] text-slate-500">{n.category}</span>
                        {!n.is_read && (
                          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.dot}`} />
                        )}
                      </div>
                      <p className={[
                        "text-xs font-medium leading-tight",
                        n.is_read ? "text-slate-400" : "text-slate-200",
                      ].join(" ")}>
                        {n.title}
                      </p>
                      {n.content && (
                        <p className="text-xs text-slate-500 mt-0.5 leading-relaxed line-clamp-2">
                          {n.content}
                        </p>
                      )}
                      <p className="text-[10px] text-slate-600 mt-1">
                        {formatRelative(n.created_at)}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Bell button — exported for Layout header
// ─────────────────────────────────────────────
export function NotificationBell() {
  const { unreadCount } = useNotifications();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Connect WebSocket at bell mount
  useNotifWebSocket();

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative p-2 rounded-lg bg-white/5 border border-white/10 text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-colors"
        title="通知中心"
        aria-label="通知中心"
      >
        {/* Bell icon */}
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {/* Unread badge */}
        {unreadCount > 0 && (
          <span
            className={[
              "absolute -top-1 -right-1 min-w-[16px] h-4 rounded-full text-white",
              "text-[9px] font-bold flex items-center justify-center px-0.5 leading-none",
              unreadCount > 0 ? LEVEL_STYLES.P0.badge : "",
            ].join(" ")}
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && <NotificationDropdown onClose={() => setOpen(false)} />}
    </div>
  );
}
