/**
 * AssistPanel — AI 助手聊天面板.
 *
 * Frontend Design v3 §2.3 — 3 modes (floating / embedded / inline) + 4 entry points:
 *   1. Layout floating button (Cmd+J global shortcut)
 *   2. PipelineConsole 5th tab "AI 助手" (embedded)
 *   3. StrategyWorkspace placeholder (embedded)
 *   4. FactorLab placeholder (embedded)
 *
 * AI Boundary (CRIT ops NEVER LLM-triggered):
 *   ❌ Block: execute_phase / env_flip / emergency_close_all / pause_trading / l4_force_reset
 *   ⚠️ Compose: l4_approve / drift_fix / threshold_change (用户最终确认)
 *   ✅ Direct: cancel_single_order / factor_archive / report_generate / explain-only
 *
 * 当前状态: 后端 stub 模式, 未真调 LLM (待 F-S7-001 修复 + AI_ASSIST_ENABLED).
 */

import { useEffect, useRef, useState } from "react";
import { Send, Bot, User, X, Sparkles, AlertTriangle } from "lucide-react";
import {
  postChat,
  getChatStatus,
  type AssistContext,
  type AssistDomain,
  type ChatMessageDto,
  type ChatStatus,
} from "@/api/agent";
import { C } from "@/theme";

export type AssistMode = "floating" | "embedded" | "inline";

interface AssistPanelProps {
  context: AssistContext;
  mode?: AssistMode;
  onClose?: () => void;
}

export function AssistPanel({ context, mode = "embedded", onClose }: AssistPanelProps) {
  const [messages, setMessages] = useState<ChatMessageDto[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Fetch chat enable status once
  useEffect(() => {
    getChatStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  const send = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    const userMsg: ChatMessageDto = { role: "user", content: trimmed };
    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const resp = await postChat({ messages: nextMessages, context });
      setMessages([...nextMessages, { role: "assistant", content: resp.reply }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "请求失败";
      setError(`AI 助手请求失败: ${msg}`);
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: `⚠️ 请求失败: ${msg}\n\n请检查后端 /api/agent/chat 端点是否可达.`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  // Determine container styles per mode
  const containerStyle: React.CSSProperties =
    mode === "floating"
      ? {
          position: "fixed",
          bottom: 20,
          right: 20,
          width: 420,
          height: 560,
          background: C.bg1,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          boxShadow: "0 10px 40px rgba(0,0,0,0.5)",
          zIndex: 40,
          display: "flex",
          flexDirection: "column",
        }
      : {
          background: C.bg1,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          height: mode === "embedded" ? 480 : 360,
          display: "flex",
          flexDirection: "column",
        };

  return (
    <div style={containerStyle}>
      {/* Header */}
      <div
        className="flex items-center gap-2 px-4 py-2.5"
        style={{ borderBottom: `1px solid ${C.border}` }}
      >
        <Sparkles size={14} color={C.accent} />
        <div className="flex-1" style={{ fontSize: 13, color: C.text1, fontWeight: 600 }}>
          AI 助手
        </div>
        <span
          className="px-2 py-0.5 rounded"
          style={{
            fontSize: 9,
            color: status?.enabled ? C.up : C.text4,
            background: status?.enabled ? `${C.up}15` : C.bg3,
            fontFamily: C.mono,
          }}
          title={status?.enabled ? "实时 LLM 已启用" : "Stub 模式 (LLM 未启用)"}
        >
          {status?.mode ?? "stub"}
        </span>
        <span
          className="px-2 py-0.5 rounded"
          style={{
            fontSize: 9,
            color: C.text3,
            background: C.bg2,
            fontFamily: C.mono,
          }}
        >
          @{context.page}
        </span>
        {mode === "floating" && onClose && (
          <button
            onClick={onClose}
            className="ml-1 cursor-pointer"
            style={{ background: "transparent", border: "none", color: C.text3 }}
            title="关闭 (Esc)"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Stub mode banner */}
      {status && !status.enabled && (
        <div
          className="px-3 py-1.5 flex items-center gap-2"
          style={{
            background: `${C.warn}10`,
            borderBottom: `1px solid ${C.warn}30`,
            fontSize: 10,
            color: C.warn,
          }}
        >
          <AlertTriangle size={11} />
          <span>Stub 模式 · 不真调 LLM. 启用见 backend/.env AI_ASSIST_ENABLED</span>
        </div>
      )}

      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-3 py-3 space-y-3"
        style={{ background: C.bg0 }}
      >
        {messages.length === 0 && (
          <div
            className="text-center py-8"
            style={{ fontSize: 11, color: C.text4, lineHeight: 1.6 }}
          >
            <Bot size={20} color={C.text4} className="mx-auto mb-2" />
            <div style={{ color: C.text3, fontSize: 12, marginBottom: 6 }}>
              在此询问 {context.page} 相关问题
            </div>
            <div>提示: 解释因子 / 分析回测 / 排查告警 / 等</div>
            {context.entity_id && (
              <div className="mt-2" style={{ fontFamily: C.mono, color: C.text4 }}>
                当前 entity: {context.entity_id}
              </div>
            )}
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {loading && (
          <div className="flex items-center gap-2" style={{ fontSize: 11, color: C.text4 }}>
            <Bot size={12} />
            <span className="animate-pulse">AI 思考中...</span>
          </div>
        )}
        {error && (
          <div
            className="px-2 py-1 rounded"
            style={{ background: `${C.up}10`, fontSize: 10, color: C.up }}
          >
            {error}
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="p-2.5" style={{ borderTop: `1px solid ${C.border}` }}>
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="问问 AI ... (Enter 发送, Shift+Enter 换行)"
            rows={2}
            className="flex-1 rounded-lg px-3 py-2"
            style={{
              background: C.bg3,
              border: `1px solid ${C.border}`,
              color: C.text1,
              fontSize: 12,
              outline: "none",
              resize: "none",
              fontFamily: C.font,
            }}
          />
          <button
            onClick={() => void send()}
            disabled={!input.trim() || loading}
            className="flex items-center justify-center rounded-lg px-3"
            style={{
              background: !input.trim() || loading ? C.bg3 : C.accent,
              color: !input.trim() || loading ? C.text4 : "#fff",
              border: "none",
              cursor: !input.trim() || loading ? "not-allowed" : "pointer",
              height: 38,
              width: 38,
            }}
            title="发送 (Enter)"
          >
            <Send size={14} />
          </button>
        </div>
        <div className="mt-1.5 flex items-center justify-between" style={{ fontSize: 9, color: C.text4 }}>
          <span>
            CRIT ops 禁止 LLM 触发 (env_flip / execute / emergency_close)
          </span>
          {messages.length > 0 && (
            <button
              onClick={() => setMessages([])}
              className="cursor-pointer"
              style={{ background: "transparent", border: "none", color: C.text4 }}
            >
              清空
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessageDto }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className="flex items-center justify-center rounded-full shrink-0"
        style={{
          background: isUser ? C.accent : C.bg2,
          width: 22,
          height: 22,
        }}
      >
        {isUser ? <User size={12} color="#fff" /> : <Bot size={12} color={C.text3} />}
      </div>
      <div
        className="px-3 py-2 rounded-lg"
        style={{
          background: isUser ? `${C.accent}15` : C.bg2,
          border: `1px solid ${isUser ? `${C.accent}30` : C.border}`,
          maxWidth: "85%",
          fontSize: 12,
          color: C.text1,
          lineHeight: 1.55,
          whiteSpace: "pre-wrap",
        }}
      >
        {message.content}
      </div>
    </div>
  );
}

/**
 * AssistPanel floating mode launcher — Layout 接入 Cmd+J 全局快捷键.
 *
 * 用法 (Layout.tsx):
 *   const [open, setOpen] = useState(false);
 *   // 监听 Cmd+J + provide page detection
 *   return <FloatingAssistLauncher />;
 */
export function FloatingAssistLauncher({
  detectPage,
}: {
  detectPage?: () => AssistDomain;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Cmd+J (macOS) / Ctrl+J (Windows/Linux)
      if (e.key === "j" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  // Auto-detect current page from URL
  const page: AssistDomain = detectPage ? detectPage() : detectFromPath();

  return (
    <>
      {/* Floating button (bottom-right) */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed cursor-pointer rounded-full flex items-center justify-center shadow-lg"
          style={{
            bottom: 24,
            right: 24,
            width: 48,
            height: 48,
            background: C.accent,
            border: "none",
            color: "#fff",
            zIndex: 30,
            boxShadow: `0 4px 20px ${C.accent}50`,
          }}
          title="AI 助手 (Cmd+J / Ctrl+J)"
        >
          <Sparkles size={18} />
        </button>
      )}

      {/* Floating panel */}
      {open && (
        <AssistPanel
          context={{ page }}
          mode="floating"
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function detectFromPath(): AssistDomain {
  const path = window.location.pathname;
  if (path.includes("risk")) return "risk";
  if (path.includes("factor")) return "factor";
  if (path.includes("execution")) return "execution";
  if (path.includes("strateg")) return "strategy";
  if (path.includes("backtest")) return "backtest";
  if (path.includes("pipeline")) return "pipeline";
  if (path.includes("dashboard") || path === "/") return "dashboard";
  return "general";
}
