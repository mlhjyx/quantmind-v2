import React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRiskEventsSSE } from "@/hooks/useRiskEventsSSE";

type Listener = (event: MessageEvent) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly listeners = new Map<string, Listener[]>();
  readonly close = vi.fn();
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;

  constructor(
    readonly url: string,
    readonly options?: EventSourceInit,
  ) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    const wrapped: Listener =
      typeof listener === "function"
        ? (event) => listener(event)
        : (event) => listener.handleEvent(event);
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), wrapped]);
  }

  emit(type: string, data?: unknown) {
    const event = { data: data === undefined ? "" : JSON.stringify(data) } as MessageEvent;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

function setRuntimeApiBase(apiBaseUrl: string) {
  (window as unknown as { __APP_CONFIG__?: { apiBaseUrl?: string } }).__APP_CONFIG__ = {
    apiBaseUrl,
  };
}

function RiskEventsProbe() {
  const { events, isConnected, lastHeartbeatAt, error } = useRiskEventsSSE({
    maxBuffer: 1,
    severity: "P0",
  });

  return (
    <div>
      <span data-testid="connected">{String(isConnected)}</span>
      <span data-testid="event-count">{events.length}</span>
      <span data-testid="latest-rule">{events.at(-1)?.rule_id ?? ""}</span>
      <span data-testid="heartbeat">{lastHeartbeatAt?.toISOString() ?? ""}</span>
      <span data-testid="error">{error ?? ""}</span>
    </div>
  );
}

describe("useRiskEventsSSE", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    setRuntimeApiBase("/api");
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    delete (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__;
  });

  it("subscribes to the risk-events SSE endpoint with credentials", async () => {
    const { unmount } = render(<RiskEventsProbe />);

    expect(FakeEventSource.instances).toHaveLength(1);
    const source = FakeEventSource.instances[0]!;
    expect(source.url).toBe("/api/sse/risk-events?severity=P0");
    expect(source.options).toEqual({ withCredentials: true });

    act(() => {
      source.onopen?.();
      source.emit("connected");
      source.emit("risk_event", {
        id: "evt-1",
        strategy_id: null,
        rule_id: "L1_STOP",
        severity: "P0",
        triggered_at: "2026-06-01T11:00:00Z",
        code: "000001.SZ",
        reason: "drawdown",
        action_taken: "STAGED",
      });
      source.emit("heartbeat", { ts: "2026-06-01T11:01:00.000Z" });
      source.emit("error", { error: "poll failed", will_retry: true });
    });

    await waitFor(() => expect(screen.getByTestId("connected")).toHaveTextContent("true"));
    expect(screen.getByTestId("event-count")).toHaveTextContent("1");
    expect(screen.getByTestId("latest-rule")).toHaveTextContent("L1_STOP");
    expect(screen.getByTestId("heartbeat")).toHaveTextContent("2026-06-01T11:01:00.000Z");
    expect(screen.getByTestId("error")).toHaveTextContent("poll failed");

    unmount();
    expect(source.close).toHaveBeenCalledTimes(1);
  });
});
