import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("risk management API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches status history through the risk API layer", async () => {
    const api = await import("@/api/risk");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          trade_date: "2026-05-29",
          prev_level: 0,
          new_level: 1,
          transition_type: "escalate",
          reason: "5d loss threshold",
          metrics: { loss_5d: -0.052 },
        },
      ],
    });

    expect(typeof api.fetchRiskHistory).toBe("function");
    await expect(api.fetchRiskHistory("strategy-1")).resolves.toHaveLength(1);
    expect(apiClientMock.get).toHaveBeenCalledWith("/risk/history/strategy-1", {
      params: { execution_mode: "paper", limit: 50 },
    });
  });

  it("fetches status summary through the risk API layer", async () => {
    const api = await import("@/api/risk");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        current_level: 1,
        current_level_name: "WARN",
        days_in_current_state: 3,
        total_escalations: 2,
        total_recoveries: 1,
      },
    });

    expect(typeof api.fetchRiskSummary).toBe("function");
    const result = await api.fetchRiskSummary("strategy-1", "paper");

    expect(result?.current_level).toBe(1);
    expect(apiClientMock.get).toHaveBeenCalledWith("/risk/summary/strategy-1", {
      params: { execution_mode: "paper" },
    });
  });

  it("requests L4 recovery through the risk API layer", async () => {
    const api = await import("@/api/risk");
    apiClientMock.post.mockResolvedValueOnce({
      data: { approval_id: "approval-1", status: "pending" },
    });

    expect(typeof api.requestL4Recovery).toBe("function");
    await expect(
      api.requestL4Recovery("strategy-1", "risk metrics recovered", "live"),
    ).resolves.toEqual({ approval_id: "approval-1", status: "pending" });

    expect(apiClientMock.post).toHaveBeenCalledWith(
      "/risk/l4-recovery/strategy-1",
      { reviewer_note: "risk metrics recovered" },
      { params: { execution_mode: "live" } },
    );
  });

  it("approves L4 recovery through the risk API layer", async () => {
    const api = await import("@/api/risk");
    apiClientMock.post.mockResolvedValueOnce({
      data: {
        status: "approved",
        approval_id: "approval-1",
        new_state: { level: 0, level_name: "NORMAL", position_multiplier: 1 },
      },
    });

    expect(typeof api.approveL4Recovery).toBe("function");
    await expect(
      api.approveL4Recovery("approval-1", true, "reviewed and approved"),
    ).resolves.toMatchObject({
      status: "approved",
      approval_id: "approval-1",
      new_state: { level: 0 },
    });

    expect(apiClientMock.post).toHaveBeenCalledWith("/risk/l4-approve/approval-1", {
      approved: true,
      reviewer_note: "reviewed and approved",
    });
  });

  it("normalizes raw overview scalars into dashboard metrics", async () => {
    const api = await import("@/api/risk");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        var_95: -0.0234,
        cvar_95: -0.0311,
        beta: 0.85,
        volatility_annualized: 0.1823,
        sharpe_60d: 0.94,
        max_drawdown: -0.1275,
        circuit_level: 2,
        position_multiplier: 0.5,
        data_days: 60,
        data_sufficient: true,
      },
    });

    expect(typeof api.fetchRiskOverviewDisplay).toBe("function");
    const result = await api.fetchRiskOverviewDisplay({ execution_mode: "live" });

    expect(result.metrics).toEqual([
      { label: "VaR 95%", value: "-2.34%" },
      { label: "CVaR 95%", value: "-3.11%" },
      { label: "Beta", value: "0.85" },
      { label: "年化波动", value: "18.23%" },
      { label: "60日夏普", value: "0.94" },
      { label: "最大回撤", value: "-12.75%" },
    ]);
    expect(result.var_series).toEqual([]);
    expect(result.exposure).toEqual([]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/risk/overview", {
      params: { execution_mode: "live" },
    });
  });

  it("keeps empty overview metrics empty so live can fallback to paper", async () => {
    const api = await import("@/api/risk");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        var_95: 0,
        cvar_95: 0,
        beta: 1,
        volatility_annualized: 0,
        sharpe_60d: 0,
        max_drawdown: 0,
        data_days: 0,
        data_sufficient: false,
      },
    });

    await expect(
      api.fetchRiskOverviewDisplay({ execution_mode: "live" }),
    ).resolves.toEqual({
      metrics: [],
      var_series: [],
      exposure: [],
    });
  });

  it("normalizes backend risk limit statuses for the UI", async () => {
    const api = await import("@/api/risk");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          name: "单股最大权重",
          limit: 0.1,
          current: 0.0834,
          usage_pct: 83.4,
          unit: "比例",
          status: "warning",
        },
        {
          name: "最大持仓数",
          limit: 20,
          current: 5,
          usage_pct: 25,
          unit: "只",
          status: "normal",
        },
        {
          name: "L3熔断阈值(总回撤)",
          limit: 0.15,
          current: 0.14,
          usage_pct: 93.3,
          unit: "比例",
          status: "danger",
        },
      ],
    });

    expect(typeof api.fetchRiskLimits).toBe("function");
    await expect(api.fetchRiskLimits({ execution_mode: "paper" })).resolves.toEqual([
      {
        name: "单股最大权重",
        current: "8.34%",
        limit: "10.00%",
        usage: 83.4,
        status: "warn",
      },
      {
        name: "最大持仓数",
        current: "5",
        limit: "20",
        usage: 25,
        status: "ok",
      },
      {
        name: "L3熔断阈值(总回撤)",
        current: "14.00%",
        limit: "15.00%",
        usage: 93.3,
        status: "critical",
      },
    ]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/risk/limits", {
      params: { execution_mode: "paper" },
    });
  });

  it("normalizes stress-test rows for the existing stress card", async () => {
    const api = await import("@/api/risk");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          scenario: "2015年股灾",
          period: "2015-06 ~ 2015-08",
          market_drop: -48.8,
          estimated_loss: -41.5,
          estimated_nav: 0.585,
          description: "沪深300三个月内暴跌48.8%",
          beta_used: 0.85,
        },
      ],
    });

    expect(typeof api.fetchStressTests).toBe("function");
    await expect(api.fetchStressTests({ execution_mode: "paper" })).resolves.toEqual([
      {
        scenario: "2015年股灾",
        impact: -41.5,
        probability: "历史",
        recovery: "2015-06 ~ 2015-08",
      },
    ]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/risk/stress-tests", {
      params: { execution_mode: "paper" },
    });
  });

  it("keeps RiskManagement behind src/api wrappers", () => {
    const source = readFileSync("src/pages/RiskManagement.tsx", "utf8");

    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });

  it("keeps SafetyControlPanel L4 mutations behind src/api wrappers", () => {
    const source = readFileSync("src/components/safety/SafetyControlPanel.tsx", "utf8");

    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });
});
