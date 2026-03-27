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
