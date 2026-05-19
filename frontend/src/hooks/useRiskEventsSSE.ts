/**
 * useRiskEventsSSE — Server-Sent Events subscriber for risk_event_log live stream.
 *
 * Closes P4 SSE round-2 (backend) + Session 58 round-4 frontend wire (ADR-084 Phase 1 first piece).
 *
 * Server endpoint: GET /api/sse/risk-events (auth: cookie OR header)
 * Stream events:
 *   - `connected`: initial connection ack (cursor + filter info)
 *   - `risk_event`: new risk_event_log row inserted (data = full row JSON)
 *   - `heartbeat`: 15s keepalive (sustain proxy connection)
 *   - `error`: server-side poll error (will_retry: true)
 *
 * Usage:
 *   const { events, isConnected, error } = useRiskEventsSSE({ severity: "P0" });
 *   useEffect(() => {
 *     if (events.length > 0) { showAlert(events[events.length - 1]); }
 *   }, [events]);
 *
 * 反 polling waste: 替代 react-query refetchInterval 5s for risk_event_log,
 * gives sub-second alert latency 同时 0 idle DB load.
 *
 * EventSource is native browser API — auto-reconnect on disconnect built-in.
 * withCredentials: true sends admin_token cookie (verify_admin_token on backend).
 *
 * 关联:
 * - backend/app/api/sse.py (P4 scaffold round-2)
 * - ADR-084 (Option C Hybrid real-time architecture, SSE for event streams)
 * - ISSUES_PENDING_REGISTRY §7 P4 closure (backend + frontend now both live)
 */

import { useEffect, useRef, useState } from "react";

// L2 runtime config support (sustained pattern from client.ts):
// window.__APP_CONFIG__.apiBaseUrl runtime override → SSE URL derivation
function _resolveApiBase(): string {
  const runtimeBase =
    typeof window !== "undefined" ? window.__APP_CONFIG__?.apiBaseUrl : undefined;
  return runtimeBase ?? import.meta.env.VITE_API_BASE_URL ?? "/api";
}

export interface RiskEvent {
  id: string;
  strategy_id: string | null;
  rule_id: string;
  severity: string;
  triggered_at: string;
  code: string | null;
  reason: string | null;
  action_taken: string | null;
}

interface UseRiskEventsSSEOptions {
  /** Optional severity filter (P0 / P1 / WARN / HALT — depends on risk_event_log.severity vocab) */
  severity?: string;
  /** Max events to keep in memory (default 100, FIFO drop oldest) */
  maxBuffer?: number;
  /** Enable/disable connection (default true) */
  enabled?: boolean;
}

interface UseRiskEventsSSEResult {
  events: RiskEvent[];
  isConnected: boolean;
  lastHeartbeatAt: Date | null;
  error: string | null;
  /** Force reconnect (closes + reopens EventSource) */
  reconnect: () => void;
}

export function useRiskEventsSSE(
  options: UseRiskEventsSSEOptions = {},
): UseRiskEventsSSEResult {
  const { severity, maxBuffer = 100, enabled = true } = options;

  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const [reconnectTrigger, setReconnectTrigger] = useState(0);

  const reconnect = () => setReconnectTrigger((n) => n + 1);

  useEffect(() => {
    if (!enabled) {
      setIsConnected(false);
      return;
    }

    const apiBase = _resolveApiBase();
    const url = severity
      ? `${apiBase}/sse/risk-events?severity=${encodeURIComponent(severity)}`
      : `${apiBase}/sse/risk-events`;

    // EventSource auto-reconnects on disconnect; withCredentials sends cookies.
    const es = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = es;

    es.addEventListener("connected", () => {
      setIsConnected(true);
      setError(null);
    });

    es.addEventListener("risk_event", (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as RiskEvent;
        setEvents((prev) => {
          const next = [...prev, event];
          // FIFO drop oldest if exceed maxBuffer
          return next.length > maxBuffer ? next.slice(next.length - maxBuffer) : next;
        });
      } catch (parseErr) {
        console.warn("[useRiskEventsSSE] failed to parse risk_event:", parseErr);
      }
    });

    es.addEventListener("heartbeat", (e: MessageEvent) => {
      try {
        const hb = JSON.parse(e.data) as { ts: string };
        setLastHeartbeatAt(new Date(hb.ts));
      } catch {
        setLastHeartbeatAt(new Date());
      }
    });

    es.addEventListener("error", (e: MessageEvent) => {
      // 反 silent error: surface server-side error events to caller.
      try {
        const errPayload = JSON.parse(e.data) as { error: string; will_retry: boolean };
        setError(errPayload.error);
      } catch {
        // Native EventSource error event (no data) — connection lost, will auto-reconnect
        setError(null);  // clear so callers know server-error is distinct from disconnect
      }
    });

    // Native onerror — fires on disconnect / network issue (auto-reconnect handled by EventSource)
    es.onerror = () => {
      setIsConnected(false);
      // EventSource auto-reconnects; don't set error here (caller would see noise on every transient hiccup).
    };

    es.onopen = () => {
      setIsConnected(true);
      setError(null);
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
      setIsConnected(false);
    };
  }, [enabled, severity, maxBuffer, reconnectTrigger]);

  return { events, isConnected, lastHeartbeatAt, error, reconnect };
}
