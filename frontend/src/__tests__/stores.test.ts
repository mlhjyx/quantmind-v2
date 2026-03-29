/**
 * Zustand Store 状态更新集成测试
 *
 * 覆盖:
 * - backtestStore: upsertRun / updateProgress / setStatus / setActiveRun
 * - miningStore:   upsertTask / updateTask / setActiveTask
 * - notificationStore: add / remove / clear
 *
 * 铁律5: 所有 store 接口已通过 read 验证（backtestStore.ts / miningStore.ts / notificationStore.ts）
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useBacktestStore, type BacktestRun } from "@/store/backtestStore";
import { useMiningStore, type MiningTask } from "@/store/miningStore";
import { useNotificationStore } from "@/store/notificationStore";

// ─────────────────────────────────────────────────────────────
// BacktestStore
// ─────────────────────────────────────────────────────────────

describe("useBacktestStore", () => {
  beforeEach(() => {
    // Zustand stores are module singletons — reset state before each test
    useBacktestStore.setState({ activeRunId: null, runs: {} });
  });

  const makeRun = (runId: string): BacktestRun => ({
    runId,
    strategyId: "strategy-001",
    strategyName: "v1.1 等权5因子",
    status: "running",
    progress: 0,
    startedAt: "2024-01-15T10:00:00Z",
  });

  it("upsertRun 插入新 run", () => {
    const store = useBacktestStore.getState();
    const run = makeRun("run-001");
    store.upsertRun(run);

    const state = useBacktestStore.getState();
    expect(state.runs["run-001"]).toEqual(run);
  });

  it("upsertRun 更新已存在 run（幂等）", () => {
    const store = useBacktestStore.getState();
    store.upsertRun(makeRun("run-001"));
    store.upsertRun({ ...makeRun("run-001"), progress: 50, status: "running" });

    const state = useBacktestStore.getState();
    expect(state.runs["run-001"].progress).toBe(50);
  });

  it("updateProgress 更新指定 run 的进度", () => {
    const store = useBacktestStore.getState();
    store.upsertRun(makeRun("run-002"));
    store.updateProgress("run-002", 75);

    const state = useBacktestStore.getState();
    expect(state.runs["run-002"].progress).toBe(75);
  });

  it("updateProgress 对不存在 runId 不崩溃", () => {
    const store = useBacktestStore.getState();
    // 不应抛出异常
    expect(() => store.updateProgress("nonexistent", 50)).not.toThrow();
  });

  it("setStatus 更新指定 run 的状态", () => {
    const store = useBacktestStore.getState();
    store.upsertRun(makeRun("run-003"));
    store.setStatus("run-003", "completed");

    const state = useBacktestStore.getState();
    expect(state.runs["run-003"].status).toBe("completed");
  });

  it("setActiveRun 设置和清除 activeRunId", () => {
    const store = useBacktestStore.getState();
    store.setActiveRun("run-001");
    expect(useBacktestStore.getState().activeRunId).toBe("run-001");

    store.setActiveRun(null);
    expect(useBacktestStore.getState().activeRunId).toBeNull();
  });

  it("多个 run 共存，互不覆盖", () => {
    const store = useBacktestStore.getState();
    store.upsertRun(makeRun("run-A"));
    store.upsertRun(makeRun("run-B"));
    store.updateProgress("run-A", 30);
    store.updateProgress("run-B", 60);

    const state = useBacktestStore.getState();
    expect(state.runs["run-A"].progress).toBe(30);
    expect(state.runs["run-B"].progress).toBe(60);
  });
});

// ─────────────────────────────────────────────────────────────
// MiningStore
// ─────────────────────────────────────────────────────────────

describe("useMiningStore", () => {
  beforeEach(() => {
    useMiningStore.setState({ activeTaskId: null, tasks: {} });
  });

  const makeTask = (taskId: string): MiningTask => ({
    taskId,
    engine: "gp",
    status: "running",
    progress: 0,
    generation: 1,
    totalGenerations: 50,
    discovered: 0,
    passed: 0,
    startedAt: "2024-01-15T10:00:00Z",
  });

  it("upsertTask 插入新任务", () => {
    const store = useMiningStore.getState();
    const task = makeTask("task-001");
    store.upsertTask(task);

    expect(useMiningStore.getState().tasks["task-001"]).toEqual(task);
  });

  it("updateTask 部分更新字段", () => {
    const store = useMiningStore.getState();
    store.upsertTask(makeTask("task-002"));
    store.updateTask("task-002", { progress: 40, discovered: 5, passed: 2 });

    const state = useMiningStore.getState().tasks["task-002"];
    expect(state.progress).toBe(40);
    expect(state.discovered).toBe(5);
    expect(state.passed).toBe(2);
    // 未更新字段保持原值
    expect(state.engine).toBe("gp");
  });

  it("updateTask 对不存在 taskId 不崩溃", () => {
    const store = useMiningStore.getState();
    expect(() => store.updateTask("nonexistent", { progress: 10 })).not.toThrow();
  });

  it("setActiveTask 设置和清除 activeTaskId", () => {
    const store = useMiningStore.getState();
    store.setActiveTask("task-001");
    expect(useMiningStore.getState().activeTaskId).toBe("task-001");

    store.setActiveTask(null);
    expect(useMiningStore.getState().activeTaskId).toBeNull();
  });

  it("completed 状态正确设置", () => {
    const store = useMiningStore.getState();
    store.upsertTask(makeTask("task-003"));
    store.updateTask("task-003", {
      status: "completed",
      progress: 100,
      completedAt: "2024-01-15T12:00:00Z",
    });

    const state = useMiningStore.getState().tasks["task-003"];
    expect(state.status).toBe("completed");
    expect(state.progress).toBe(100);
  });
});

// ─────────────────────────────────────────────────────────────
// NotificationStore
// ─────────────────────────────────────────────────────────────

describe("useNotificationStore", () => {
  beforeEach(() => {
    useNotificationStore.setState({ notifications: [] });
  });

  it("add 插入通知，自动生成唯一 id", () => {
    const store = useNotificationStore.getState();
    store.add({ type: "success", title: "因子审批通过" });

    const state = useNotificationStore.getState();
    expect(state.notifications).toHaveLength(1);
    expect(state.notifications[0].id).toBeTruthy();
    expect(state.notifications[0].title).toBe("因子审批通过");
  });

  it("add 多条通知，id 互不相同", () => {
    const store = useNotificationStore.getState();
    store.add({ type: "info", title: "通知1" });
    store.add({ type: "warning", title: "通知2" });

    const state = useNotificationStore.getState();
    expect(state.notifications).toHaveLength(2);
    const ids = state.notifications.map((n) => n.id);
    expect(new Set(ids).size).toBe(2);
  });

  it("remove 按 id 删除指定通知", () => {
    const store = useNotificationStore.getState();
    store.add({ type: "error", title: "P0告警", duration: 0 });

    const { notifications } = useNotificationStore.getState();
    const id = notifications[0].id;
    useNotificationStore.getState().remove(id);

    expect(useNotificationStore.getState().notifications).toHaveLength(0);
  });

  it("clear 清空所有通知", () => {
    const store = useNotificationStore.getState();
    store.add({ type: "info", title: "A" });
    store.add({ type: "info", title: "B" });
    store.add({ type: "info", title: "C" });

    useNotificationStore.getState().clear();
    expect(useNotificationStore.getState().notifications).toHaveLength(0);
  });

  it("remove 不存在 id 不崩溃", () => {
    const store = useNotificationStore.getState();
    expect(() => store.remove("nonexistent-id")).not.toThrow();
  });
});
