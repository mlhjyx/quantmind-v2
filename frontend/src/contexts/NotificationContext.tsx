import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";

export type NotificationLevel = "P0" | "P1" | "P2" | "P3";

export interface Notification {
  id: string;
  level: NotificationLevel;
  category: string;
  title: string;
  content?: string;
  link?: string;
  is_read: boolean;
  created_at: string;
}

export interface Toast {
  id: string;
  level: NotificationLevel;
  title: string;
  content?: string;
  link?: string;
}

interface NotificationContextValue {
  notifications: Notification[];
  toasts: Toast[];
  unreadCount: number;
  addToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  addNotification: (n: Omit<Notification, "id" | "is_read" | "created_at">) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

// ── Seed mock notifications ──
function makeMockNotifications(): Notification[] {
  const now = new Date();
  function daysAgo(d: number) {
    const dt = new Date(now);
    dt.setDate(dt.getDate() - d);
    return dt.toISOString();
  }
  return [
    {
      id: "n1",
      level: "P0",
      category: "风控",
      title: "熔断告警: L2触发",
      content: "组合回撤超过-8%，已自动降仓至50%。需人工确认恢复。",
      link: "/settings/risk",
      is_read: false,
      created_at: daysAgo(0),
    },
    {
      id: "n2",
      level: "P1",
      category: "PT",
      title: "Paper Trading: 调仓信号生成",
      content: "v1.1策略生成调仓信号，待执行4只股票。",
      link: "/dashboard/astock",
      is_read: false,
      created_at: daysAgo(0),
    },
    {
      id: "n3",
      level: "P2",
      category: "因子",
      title: "因子体检完成",
      content: "34个因子正常，2个因子IC衰减超阈值，建议复查。",
      link: "/factors",
      is_read: false,
      created_at: daysAgo(1),
    },
    {
      id: "n4",
      level: "P2",
      category: "回测",
      title: "回测任务完成",
      content: "动量反转v3回测完成，Sharpe 1.12，MDD -18.4%。",
      link: "/backtest/config",
      is_read: false,
      created_at: daysAgo(1),
    },
    {
      id: "n5",
      level: "P3",
      category: "系统",
      title: "数据更新完成",
      content: "日频行情数据已同步至2026-03-27。",
      is_read: true,
      created_at: daysAgo(1),
    },
    {
      id: "n6",
      level: "P1",
      category: "AI",
      title: "GP因子挖掘任务完成",
      content: "本次挖掘发现3个候选因子，IC均值0.032，建议进入审批流程。",
      link: "/mining",
      is_read: true,
      created_at: daysAgo(2),
    },
    {
      id: "n7",
      level: "P3",
      category: "系统",
      title: "备份完成",
      content: "PostgreSQL全量备份成功，大小 2.1GB。",
      is_read: true,
      created_at: daysAgo(2),
    },
  ];
}

let _idCounter = 100;
function nextId() {
  return `gen_${++_idCounter}`;
}

// Auto-dismiss timers: P3=3s, P1/P2=5s, P0=never
const DISMISS_MS: Record<NotificationLevel, number | null> = {
  P0: null,
  P1: 5000,
  P2: 3000,
  P3: 3000,
};

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>(
    makeMockNotifications
  );
  const [toasts, setToasts] = useState<Toast[]>([]);

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const addToast = useCallback((toast: Omit<Toast, "id">) => {
    const id = nextId();
    setToasts((prev) => [{ ...toast, id }, ...prev].slice(0, 3));
    const ms = DISMISS_MS[toast.level];
    if (ms !== null) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, ms);
    }
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const markRead = useCallback((id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
    );
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
  }, []);

  const addNotification = useCallback(
    (n: Omit<Notification, "id" | "is_read" | "created_at">) => {
      const id = nextId();
      const newN: Notification = {
        ...n,
        id,
        is_read: false,
        created_at: new Date().toISOString(),
      };
      setNotifications((prev) => [newN, ...prev]);
      // Also show as toast
      addToast({ level: n.level, title: n.title, content: n.content, link: n.link });
    },
    [addToast]
  );

  // Suppress unused-effect lint — keep for future WebSocket integration
  useEffect(() => {}, []);

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        toasts,
        unreadCount,
        addToast,
        dismissToast,
        markRead,
        markAllRead,
        addNotification,
      }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications(): NotificationContextValue {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error("useNotifications must be used inside NotificationProvider");
  return ctx;
}
