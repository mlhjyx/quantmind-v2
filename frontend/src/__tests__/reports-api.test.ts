/**
 * reports.ts API wrapper tests (iter 35).
 *
 * Coverage:
 *   - generateReport: POST /reports/generate with/without strategy_id; mode default; response shape
 *   - getLatestReport: GET /reports/{sid}/latest with execution_mode param
 *   - listStrategyReports: GET /reports/{sid}/list with/without options; limit + mode filter passthrough
 *
 * Uses vitest mock for apiClient (no real HTTP requests). Mirrors pipeline-api.test.ts pattern.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import apiClient from "@/api/client";
import {
  generateReport,
  getLatestReport,
  listStrategyReports,
  type GenerateReportResponse,
  type ReportArtifact,
  type ReportListingRow,
} from "@/api/reports";

const post = apiClient.post as unknown as Mock;
const get = apiClient.get as unknown as Mock;

const sampleArtifact: ReportArtifact = {
  schema_version: "1.0",
  strategy_id: "sid-foo",
  execution_mode: "paper",
  target_date_shanghai: "2026-05-24",
  generated_at_utc: "2026-05-24T10:00:00+00:00",
  data_available: true,
  summary: { days: 60, sharpe: 1.5, mdd: -0.08, total_return: 0.12, latest_nav: 1.12 },
  latest_nav: {
    trade_date: "2026-04-28",
    nav: 1.05,
    daily_return: 0.005,
    cumulative_return: 0.05,
    drawdown: -0.02,
    cash_ratio: 0.4,
    cash: 400_000,
    position_count: 15,
    turnover: 0.15,
    benchmark_nav: 1.03,
  },
  recent_trades: [
    {
      trade_date: "2026-04-28",
      code: "000001.SZ",
      direction: "buy",
      quantity: 100,
      fill_price: 15.5,
      signal_price: 15.4,
      reject_reason: null,
    },
  ],
  trades_count: 1,
};

describe("generateReport", () => {
  beforeEach(() => vi.clearAllMocks());

  it("POSTs /reports/generate with execution_mode default 'paper' and no strategy_id in params", async () => {
    const resp: GenerateReportResponse = {
      task_id: "celery-task-id-abc",
      status: "dispatched",
      message: "派发到 Celery worker",
      strategy_id: "default-sid",
      execution_mode: "paper",
    };
    post.mockResolvedValue({ data: resp });

    const result = await generateReport();

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body, opts] = post.mock.calls[0];
    expect(url).toBe("/reports/generate");
    expect(body).toBeNull();
    expect(opts.params).toEqual({ execution_mode: "paper" });
    expect(result).toEqual(resp);
    // 反 regression to pre-iter-30 random uuid4 stub: task_id must be from response
    expect(result.task_id).toBe("celery-task-id-abc");
    expect(result.status).toBe("dispatched");
  });

  it("includes strategy_id in params when provided", async () => {
    post.mockResolvedValue({
      data: { task_id: "tid-2", status: "dispatched", message: "", strategy_id: "sid-bar", execution_mode: "live" },
    });

    await generateReport("sid-bar", "live");

    const opts = post.mock.calls[0][2];
    expect(opts.params).toEqual({ execution_mode: "live", strategy_id: "sid-bar" });
  });
});

describe("getLatestReport", () => {
  beforeEach(() => vi.clearAllMocks());

  it("GETs /reports/{sid}/latest with execution_mode param", async () => {
    get.mockResolvedValue({ data: sampleArtifact });

    const result = await getLatestReport("sid-foo");

    expect(get).toHaveBeenCalledTimes(1);
    const [url, opts] = get.mock.calls[0];
    expect(url).toBe("/reports/sid-foo/latest");
    expect(opts.params).toEqual({ execution_mode: "paper" });
    expect(result.schema_version).toBe("1.0");
    expect(result.summary?.sharpe).toBe(1.5);
    expect(result.recent_trades).toHaveLength(1);
    // Reviewer P0-1 regression guard from iter 30: trade rows use direction/fill_price NOT side/price
    expect(result.recent_trades[0].direction).toBe("buy");
    expect(result.recent_trades[0].fill_price).toBe(15.5);
  });

  it("supports live execution_mode override", async () => {
    get.mockResolvedValue({ data: { ...sampleArtifact, execution_mode: "live" } });

    await getLatestReport("sid-foo", "live");

    const opts = get.mock.calls[0][1];
    expect(opts.params).toEqual({ execution_mode: "live" });
  });
});

describe("listStrategyReports", () => {
  beforeEach(() => vi.clearAllMocks());

  it("GETs /reports/{sid}/list with no params when no options", async () => {
    const rows: ReportListingRow[] = [];
    get.mockResolvedValue({ data: rows });

    const result = await listStrategyReports("sid-foo");

    expect(get).toHaveBeenCalledTimes(1);
    const [url, opts] = get.mock.calls[0];
    expect(url).toBe("/reports/sid-foo/list");
    expect(opts.params).toEqual({});
    expect(result).toEqual([]);
  });

  it("passes execution_mode + limit params through", async () => {
    get.mockResolvedValue({ data: [] });

    await listStrategyReports("sid-foo", { execution_mode: "live", limit: 5 });

    const opts = get.mock.calls[0][1];
    expect(opts.params).toEqual({ execution_mode: "live", limit: 5 });
  });

  it("returns array with corrupt-marked rows preserved (反 silent skip from iter 32)", async () => {
    const rows: ReportListingRow[] = [
      {
        strategy_id: "sid-foo",
        execution_mode: "paper",
        target_date: "2026-05-23",
        artifact_path: "/reports/sid-foo_2026-05-23_paper.json",
        mtime_utc: "2026-05-23T10:00:00+00:00",
        summary: { days: 60, sharpe: 1.2, mdd: -0.05, total_return: 0.08, latest_nav: 1.08 },
        _corrupt: false,
      },
      {
        strategy_id: "sid-foo",
        execution_mode: "paper",
        target_date: "2026-05-22",
        artifact_path: "/reports/sid-foo_2026-05-22_paper.json",
        mtime_utc: "2026-05-22T10:00:00+00:00",
        summary: null,
        _corrupt: true,
        _corrupt_reason: "JSONDecodeError: Expecting value",
      },
    ];
    get.mockResolvedValue({ data: rows });

    const result = await listStrategyReports("sid-foo");

    expect(result).toHaveLength(2);
    expect(result[0]._corrupt).toBe(false);
    expect(result[1]._corrupt).toBe(true);
    expect(result[1].summary).toBeNull();
    expect(result[1]._corrupt_reason).toContain("JSONDecodeError");
  });

  it("handles 200 empty list (NOT 404, different semantic from /latest)", async () => {
    get.mockResolvedValue({ data: [] });

    const result = await listStrategyReports("sid-none");

    expect(result).toEqual([]);
    expect(get).toHaveBeenCalledTimes(1);
  });
});
