import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
  type NotificationLevel,
} from "@/api/notifications";

export type { NotificationLevel };
export type Notification = NotificationItem;

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
  isLoading: boolean;
  error: string | null;
  addToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  addNotification: (n: Omit<Notification, "id" | "is_read" | "created_at">) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

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
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadNotifications = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetchNotifications({ limit: 50, offset: 0 });
      setNotifications(response.items);
      setUnreadCount(response.unread_count);
      setError(null);
    } catch {
      setNotifications([]);
      setUnreadCount(0);
      setError("通知加载失败");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      setIsLoading(true);
      try {
        const response = await fetchNotifications({ limit: 50, offset: 0 });
        if (cancelled) return;
        setNotifications(response.items);
        setUnreadCount(response.unread_count);
        setError(null);
      } catch {
        if (cancelled) return;
        setNotifications([]);
        setUnreadCount(0);
        setError("通知加载失败");
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, []);

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
    const target = notifications.find((n) => n.id === id);
    if (!target || target.is_read) {
      return;
    }
    setUnreadCount((prev) => Math.max(0, prev - 1));
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
    );
    void markNotificationRead(id).catch(() => {
      setError("通知标记失败");
      void loadNotifications();
    });
  }, [loadNotifications, notifications]);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    setUnreadCount(0);
    void markAllNotificationsRead().catch(() => {
      setError("通知标记失败");
      void loadNotifications();
    });
  }, [loadNotifications]);

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
      setUnreadCount((prev) => prev + 1);
      // Also show as toast
      addToast({ level: n.level, title: n.title, content: n.content, link: n.link });
    },
    [addToast]
  );

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        toasts,
        unreadCount,
        isLoading,
        error,
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
