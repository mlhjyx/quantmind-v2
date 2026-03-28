import { useState, useEffect, useRef, useCallback } from "react";
import { io, Socket } from "socket.io-client";
import { getBacktestProgress, type BacktestProgress } from "@/api/backtest";

const WS_URL = import.meta.env.VITE_WS_URL ?? "";
const POLL_INTERVAL_MS = 2000;

interface UseBacktestProgressOptions {
  runId: string | undefined;
  enabled?: boolean;
}

interface UseBacktestProgressResult {
  progress: BacktestProgress | null;
  isConnected: boolean;
  isPolling: boolean;
  error: string | null;
}

export function useBacktestProgress({
  runId,
  enabled = true,
}: UseBacktestProgressOptions): UseBacktestProgressResult {
  const [progress, setProgress] = useState<BacktestProgress | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const socketRef = useRef<Socket | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wsFailedRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    setIsPolling(false);
  }, []);

  const startPolling = useCallback(() => {
    if (!runId || pollTimerRef.current) return;
    setIsPolling(true);

    const poll = async () => {
      try {
        const data = await getBacktestProgress(runId);
        setProgress(data);
        setError(null);
        // Stop polling once terminal state reached
        if (data.status === "completed" || data.status === "failed" || data.status === "cancelled") {
          stopPolling();
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "轮询失败");
      }
    };

    poll();
    pollTimerRef.current = setInterval(poll, POLL_INTERVAL_MS);
  }, [runId, stopPolling]);

  useEffect(() => {
    if (!runId || !enabled) return;

    // Try WebSocket first
    const socket = io(`${WS_URL}/ws/backtest`, {
      transports: ["websocket"],
      reconnection: true,
      reconnectionAttempts: 3,
      reconnectionDelay: 1000,
      timeout: 5000,
    });

    socketRef.current = socket;

    const connectTimeout = setTimeout(() => {
      if (!socket.connected) {
        wsFailedRef.current = true;
        socket.disconnect();
        startPolling();
      }
    }, 5000);

    socket.on("connect", () => {
      clearTimeout(connectTimeout);
      setIsConnected(true);
      setIsPolling(false);
      wsFailedRef.current = false;
      // Subscribe to this run's progress
      socket.emit("subscribe", { run_id: runId });
    });

    socket.on("disconnect", () => {
      setIsConnected(false);
      // Fall back to polling if not in terminal state
      if (progress?.status !== "completed" && progress?.status !== "failed") {
        wsFailedRef.current = true;
        startPolling();
      }
    });

    socket.on("connect_error", () => {
      clearTimeout(connectTimeout);
      wsFailedRef.current = true;
      setIsConnected(false);
      socket.disconnect();
      startPolling();
    });

    socket.on("backtest:progress", (data: BacktestProgress) => {
      setProgress(data);
      setError(null);
      if (data.status === "completed" || data.status === "failed" || data.status === "cancelled") {
        socket.disconnect();
      }
    });

    socket.on("backtest:error", (data: { message: string }) => {
      setError(data.message);
    });

    return () => {
      clearTimeout(connectTimeout);
      socket.disconnect();
      socketRef.current = null;
      stopPolling();
    };
  }, [runId, enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  return { progress, isConnected, isPolling, error };
}
