import { useEffect, useRef, useCallback } from "react";
import { io, Socket } from "socket.io-client";

// L2 fix (Session 58 round-2): runtime config support (same pattern as client.ts).
const _wsRuntimeConfig = (typeof window !== "undefined" ? window.__APP_CONFIG__ : undefined) ?? {};
const WS_URL = _wsRuntimeConfig.wsUrl ?? import.meta.env.VITE_WS_URL ?? "";

interface UseWebSocketOptions {
  namespace?: string;
  enabled?: boolean;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (err: Error) => void;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { namespace = "", enabled = true, onConnect, onDisconnect, onError } = options;
  const socketRef = useRef<Socket | null>(null);
  const listenersRef = useRef<Map<string, ((...args: unknown[]) => void)[]>>(new Map());

  // L3 fix (Session 58 round-2, ISSUES_PENDING_REGISTRY §10 L3): callback refs
  // 反 stale closure. 旧 pattern dep array `[enabled, namespace]` with eslint-disable
  // meant callbacks captured at first mount only — inline arrow function callers got
  // stale references. Refs let callbacks update without re-subscribing socket.
  const onConnectRef = useRef(onConnect);
  const onDisconnectRef = useRef(onDisconnect);
  const onErrorRef = useRef(onError);
  onConnectRef.current = onConnect;
  onDisconnectRef.current = onDisconnect;
  onErrorRef.current = onError;

  useEffect(() => {
    if (!enabled) return;

    const socket = io(`${WS_URL}${namespace}`, {
      // L3 fix: add polling fallback for firewall/proxy environments that block WS upgrade.
      // 反 silent connect failure on corporate network. socket.io auto-upgrades to WS when possible.
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    socketRef.current = socket;

    // L3 fix: use refs for callbacks (反 stale closure on inline arrow functions).
    socket.on("connect", () => onConnectRef.current?.());
    socket.on("disconnect", () => onDisconnectRef.current?.());
    socket.on("connect_error", (err) => {
      // L3 fix: surface to console even when no onError handler (反 silent fail at boundary).
      if (onErrorRef.current) {
        onErrorRef.current(err);
      } else {
        console.warn(`[useWebSocket] connect_error namespace=${namespace}:`, err.message);
      }
    });

    // Re-attach any listeners registered before connection
    listenersRef.current.forEach((handlers, event) => {
      handlers.forEach((h) => socket.on(event, h as Parameters<typeof socket.on>[1]));
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [enabled, namespace]);

  const on = useCallback(<T = unknown>(event: string, handler: (data: T) => void) => {
    const h = handler as (...args: unknown[]) => void;
    const existing = listenersRef.current.get(event) ?? [];
    listenersRef.current.set(event, [...existing, h]);
    socketRef.current?.on(event, h as Parameters<Socket["on"]>[1]);
  }, []);

  const off = useCallback(<T = unknown>(event: string, handler: (data: T) => void) => {
    const h = handler as (...args: unknown[]) => void;
    const existing = listenersRef.current.get(event) ?? [];
    listenersRef.current.set(event, existing.filter((fn) => fn !== h));
    socketRef.current?.off(event, h as Parameters<Socket["off"]>[1]);
  }, []);

  const emit = useCallback((event: string, data?: unknown) => {
    socketRef.current?.emit(event, data);
  }, []);

  const isConnected = () => socketRef.current?.connected ?? false;

  return { on, off, emit, isConnected };
}
