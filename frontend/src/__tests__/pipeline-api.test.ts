/**
 * pipeline.ts API 函数单元测试
 *
 * Phase K 修复回归守门: triggerPipeline 必须带 {engine, config} body。
 * 旧实现 `apiClient.post("/pipeline/trigger")` 不带 body → backend
 * TriggerPipelineRequest 校验失败 422。本测试锁定 body 始终存在。
 *
 * 使用 vitest mock 拦截 apiClient，不发真实 HTTP 请求。
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";

// Mock apiClient — pipeline.ts 内部 `import apiClient from "./client"` 解析到同一模块。
vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import apiClient from "@/api/client";
import {
  triggerPipeline,
  getAutomationLevel,
  pausePipeline,
  resumePipeline,
  type TriggerPipelineResult,
} from "@/api/pipeline";

const post = apiClient.post as unknown as Mock;
const get = apiClient.get as unknown as Mock;

const sampleResult: TriggerPipelineResult = {
  run_id: "gp_2026w21_abc123",
  task_id: "task-xyz",
  engine: "gp",
  status: "running",
};

describe("triggerPipeline", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs /pipeline/trigger with a non-empty {engine, config} body", async () => {
    post.mockResolvedValue({ data: sampleResult });
    await triggerPipeline();

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/pipeline/trigger");
    // Regression guard: the old implementation sent NO body → backend 422.
    expect(body).toBeDefined();
    expect(body).toMatchObject({ engine: "gp", config: {} });
  });

  it("defaults engine to 'gp' when called with no arguments", async () => {
    post.mockResolvedValue({ data: sampleResult });
    await triggerPipeline();
    expect(post.mock.calls[0][1]).toMatchObject({ engine: "gp" });
  });

  it("forwards an explicit engine + config to the request body", async () => {
    post.mockResolvedValue({ data: { ...sampleResult, engine: "bruteforce" } });
    await triggerPipeline("bruteforce", { generations: 5 });
    expect(post.mock.calls[0][1]).toEqual({
      engine: "bruteforce",
      config: { generations: 5 },
    });
  });

  it("returns the backend TriggerPipelineResult unwrapped from res.data", async () => {
    post.mockResolvedValue({ data: sampleResult });
    const res = await triggerPipeline();
    expect(res).toEqual(sampleResult);
    expect(res.run_id).toBe("gp_2026w21_abc123");
    expect(res.task_id).toBe("task-xyz");
  });
});

describe("getAutomationLevel (D1 O8 GET consumer)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("GETs /pipeline/automation-level and returns res.data unwrapped", async () => {
    get.mockResolvedValue({ data: { level: "L2" } });
    const res = await getAutomationLevel();

    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("/pipeline/automation-level");
    expect(res).toEqual({ level: "L2" });
  });

  it("returns the backend default L0 when backend so reports", async () => {
    get.mockResolvedValue({ data: { level: "L0" } });
    const res = await getAutomationLevel();
    expect(res.level).toBe("L0");
  });
});

describe("pausePipeline (D1 O3 PN-003)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs /pipeline/pause with empty body when no reason supplied", async () => {
    post.mockResolvedValue({
      data: { paused_at: "2026-05-24T00:30:00+00:00", paused_reason: null },
    });
    const res = await pausePipeline();

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/pipeline/pause");
    expect(body).toEqual({});
    expect(res.paused_at).toBe("2026-05-24T00:30:00+00:00");
    expect(res.paused_reason).toBeNull();
  });

  it("POSTs /pipeline/pause with {reason} when reason supplied", async () => {
    post.mockResolvedValue({
      data: { paused_at: "2026-05-24T00:30:00+00:00", paused_reason: "maintenance" },
    });
    const res = await pausePipeline("maintenance");

    const [, body] = post.mock.calls[0];
    expect(body).toEqual({ reason: "maintenance" });
    expect(res.paused_reason).toBe("maintenance");
  });
});

describe("resumePipeline (D1 O3 PN-003)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs /pipeline/resume with no body and returns null state", async () => {
    post.mockResolvedValue({
      data: { paused_at: null, paused_reason: null },
    });
    const res = await resumePipeline();

    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/pipeline/resume");
    expect(res).toEqual({ paused_at: null, paused_reason: null });
  });
});
