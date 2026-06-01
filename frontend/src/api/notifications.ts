import apiClient from "./client";

export type NotificationLevel = "P0" | "P1" | "P2" | "P3";

export interface NotificationItem {
  id: string;
  level: NotificationLevel;
  category: string;
  title: string;
  content?: string;
  link?: string;
  is_read: boolean;
  is_acted?: boolean;
  market?: string;
  created_at: string;
}

export interface NotificationListParams {
  level?: NotificationLevel;
  category?: string;
  is_read?: boolean;
  limit?: number;
  offset?: number;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  limit: number;
  offset: number;
  unread_count: number;
}

export interface MarkNotificationReadResponse {
  success: boolean;
  id: string;
}

export interface MarkAllNotificationsReadResponse {
  success: boolean;
  updated_count: number;
}

interface RawNotificationItem {
  id?: unknown;
  level?: unknown;
  category?: unknown;
  title?: unknown;
  content?: unknown;
  message?: unknown;
  link?: unknown;
  target_path?: unknown;
  is_read?: unknown;
  read?: unknown;
  is_acted?: unknown;
  market?: unknown;
  created_at?: unknown;
}

interface RawNotificationListResponse {
  items?: RawNotificationItem[];
  limit?: unknown;
  offset?: unknown;
  unread_count?: unknown;
}

function compactParams(params: NotificationListParams): Record<string, string | number | boolean> {
  const compacted: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      compacted[key] = value;
    }
  }
  return compacted;
}

function requireString(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Invalid notification ${fieldName}`);
  }
  return value;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function normalizeLevel(value: unknown): NotificationLevel {
  if (value === "P0" || value === "P1" || value === "P2" || value === "P3") {
    return value;
  }
  throw new Error(`Invalid notification level: ${String(value)}`);
}

function normalizeNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function normalizeNotification(raw: RawNotificationItem): NotificationItem {
  return {
    id: requireString(raw.id, "id"),
    level: normalizeLevel(raw.level),
    category: optionalString(raw.category) ?? "system",
    title: requireString(raw.title, "title"),
    content: optionalString(raw.content) ?? optionalString(raw.message),
    link: optionalString(raw.link) ?? optionalString(raw.target_path),
    is_read: Boolean(raw.is_read ?? raw.read ?? false),
    is_acted: typeof raw.is_acted === "boolean" ? raw.is_acted : undefined,
    market: optionalString(raw.market),
    created_at: requireString(raw.created_at, "created_at"),
  };
}

export async function fetchNotifications(
  params: NotificationListParams = {},
): Promise<NotificationListResponse> {
  const compactedParams = compactParams(params);
  const { data } = await apiClient.get<RawNotificationListResponse>("/notifications", {
    params: compactedParams,
  });

  return {
    items: (data?.items ?? []).map(normalizeNotification),
    limit: normalizeNumber(data?.limit, params.limit ?? 50),
    offset: normalizeNumber(data?.offset, params.offset ?? 0),
    unread_count: normalizeNumber(data?.unread_count, 0),
  };
}

export async function markNotificationRead(
  notificationId: string,
): Promise<MarkNotificationReadResponse> {
  const id = notificationId.trim();
  if (!id) {
    throw new Error("notification id is required");
  }
  const { data } = await apiClient.put<MarkNotificationReadResponse>(
    `/notifications/${id}/read`,
  );
  return data;
}

export async function markAllNotificationsRead(): Promise<MarkAllNotificationsReadResponse> {
  const { data } = await apiClient.put<MarkAllNotificationsReadResponse>(
    "/notifications/read-all",
  );
  return data;
}
