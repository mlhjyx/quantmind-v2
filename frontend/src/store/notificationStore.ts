/**
 * notificationStore — Zustand-based transient notification SSOT.
 *
 * Distinct role vs NotificationContext (per ISSUES_PENDING_REGISTRY §4 A3 analysis):
 *   - notificationStore: Zustand, callable from anywhere (incl axios interceptors outside React)
 *   - NotificationContext: React Provider, P0-P3 persistent + Toast/Panel render
 *
 * 不能 consolidate (Phase I DEFERRED, ~4-6h refactor): apiClient axios.create() interceptor
 * 不在 React 上下文 → 不能 useContext. 真 consolidate path 需 NotificationContext 改用
 * Zustand 内部 store, or notificationStore 加 P0-P3 level.
 *
 * 关联: ISSUES_PENDING_REGISTRY §4 A3 / Frontend Design v3 §4.2 (4 → 2 distinct systems)
 */
import { create } from "zustand";

export type NotificationType = "info" | "success" | "warning" | "error";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message?: string;
  duration?: number; // ms, 0 = persistent
}

interface NotificationState {
  notifications: Notification[];
  add: (n: Omit<Notification, "id">) => void;
  remove: (id: string) => void;
  clear: () => void;
}

let _idCounter = 0;

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  add: (n) => {
    const id = `notif_${Date.now()}_${++_idCounter}`;
    set((state) => ({
      notifications: [...state.notifications, { ...n, id }],
    }));
    const duration = n.duration ?? 5000;
    if (duration > 0) {
      setTimeout(() => {
        set((state) => ({
          notifications: state.notifications.filter((x) => x.id !== id),
        }));
      }, duration);
    }
  },
  remove: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),
  clear: () => set({ notifications: [] }),
}));
