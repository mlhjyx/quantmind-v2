import { useEffect, useRef, useCallback } from "react";
import { io, Socket } from "socket.io-client";

const WS_URL = import.meta.env.VITE_WS_URL ?? "";

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

  useEffect(() => {
    if (!enabled) return;

    const socket = io(`${WS_URL}${namespace}`, {
      transports: ["websocket"],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    socketRef.current = socket;

    socket.on("connect", () => onConnect?.());
    socket.on("disconnect", () => onDisconnect?.());
    socket.on("connect_error", (err) => onError?.(err));

    // Re-attach any listeners registered before connection
    listenersRef.current.forEach((handlers, event) => {
      handlers.forEach((h) => socket.on(event, h as Parameters<typeof socket.on>[1]));
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [enabled, namespace]); // eslint-disable-line react-hooks/exhaustive-deps

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
