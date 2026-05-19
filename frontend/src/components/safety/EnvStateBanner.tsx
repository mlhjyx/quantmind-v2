/**
 * EnvStateBanner — 顶部固定 banner 显示 .env 关键字段实时状态.
 *
 * Frontend Design v3 §2.1 + §3.1.1 — Layout 顶部插入, 覆盖 35 pages.
 * LL-183 silent NOT-GATING 教训 UI 化: 用户必须时刻看到 mode + LIVE_TRADING_DISABLED.
 *
 * 渲染语义 (4 状态):
 *   - mode=paper + live_trading_disabled=true  → GREEN  safe banner
 *   - mode=live  + live_trading_disabled=false → RED + pulse 实盘 banner
 *   - mode=live  + live_trading_disabled=true  → AMBER 矛盾 banner (env mismatch)
 *   - mode=paper + live_trading_disabled=false → AMBER 矛盾 banner (env mismatch)
 *
 * Backend: GET /api/system/env-state (5s refetch).
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldCheck, Zap } from "lucide-react";
import { fetchEnvState, type EnvState } from "@/api/system";
import { C } from "@/theme";

type BannerVariant = "safe" | "live" | "mismatch" | "unknown";

function deriveVariant(state: EnvState | null): BannerVariant {
  if (!state) return "unknown";
  const live = state.mode === "live";
  const disabled = state.live_trading_disabled;
  if (!live && disabled) return "safe";
  if (live && !disabled) return "live";
  return "mismatch";
}

interface VariantStyle {
  bg: string;
  border: string;
  text: string;
  icon: React.ReactNode;
  label: string;
  pulse: boolean;
}

function variantStyle(variant: BannerVariant): VariantStyle {
  switch (variant) {
    case "safe":
      return {
        bg: `${C.down}12`,
        border: `${C.down}40`,
        text: C.down,
        icon: <ShieldCheck size={13} />,
        label: "PAPER · 安全",
        pulse: false,
      };
    case "live":
      return {
        bg: `${C.up}18`,
        border: `${C.up}55`,
        text: C.up,
        icon: <Zap size={13} />,
        label: "LIVE · 实盘",
        pulse: true,
      };
    case "mismatch":
      return {
        bg: `${C.warn}15`,
        border: `${C.warn}50`,
        text: C.warn,
        icon: <AlertTriangle size={13} />,
        label: "ENV 矛盾",
        pulse: false,
      };
    case "unknown":
    default:
      return {
        bg: C.bg2,
        border: C.border,
        text: C.text4,
        icon: <AlertTriangle size={13} />,
        label: "状态未知",
        pulse: false,
      };
  }
}

export function EnvStateBanner() {
  // Session 58 round-4 ADR-084 Phase 1: setInterval → react-query (uniform lifecycle).
  // 反 manual setInterval + alive flag duplication. react-query handles:
  // - Refetch interval (5s sustained)
  // - Stale-while-revalidate semantics
  // - Mount/unmount cleanup
  // - Dedupe concurrent queries
  // - Background pause when tab inactive (battery saving)
  const { data: state, error: queryError } = useQuery<EnvState>({
    queryKey: ["env-state"],
    queryFn: fetchEnvState,
    refetchInterval: 5_000,
    staleTime: 3_000,
  });
  const error = queryError instanceof Error ? queryError.message : queryError ? "加载失败" : null;

  const variant = deriveVariant(state ?? null);
  const style = variantStyle(variant);

  return (
    <div
      className="flex items-center gap-3 px-5 py-1.5 shrink-0"
      style={{
        background: style.bg,
        borderBottom: `1px solid ${style.border}`,
        fontSize: 11,
      }}
    >
      <div className="flex items-center gap-1.5" style={{ color: style.text, fontWeight: 600 }}>
        {style.pulse ? (
          <span className="relative flex items-center justify-center">
            <span
              className="absolute w-2 h-2 rounded-full animate-ping"
              style={{ background: style.text, opacity: 0.5 }}
            />
            <span className="relative">{style.icon}</span>
          </span>
        ) : (
          style.icon
        )}
        <span>{style.label}</span>
      </div>

      {state && (
        <>
          <span style={{ color: C.text4 }}>·</span>
          <span style={{ color: C.text3 }}>
            EXECUTION_MODE=
            <span style={{ color: state.mode === "live" ? C.up : C.down, fontFamily: C.mono, fontWeight: 600 }}>
              {state.mode}
            </span>
          </span>
          <span style={{ color: C.text4 }}>·</span>
          <span style={{ color: C.text3 }}>
            LIVE_TRADING_DISABLED=
            <span
              style={{
                color: state.live_trading_disabled ? C.down : C.up,
                fontFamily: C.mono,
                fontWeight: 600,
              }}
            >
              {String(state.live_trading_disabled)}
            </span>
          </span>
          <span style={{ color: C.text4 }}>·</span>
          <span style={{ color: C.text3, fontFamily: C.mono }}>
            QMT={state.qmt_account_id}
          </span>
          <span style={{ color: C.text4 }}>·</span>
          <span style={{ color: C.text3 }}>
            PT_TOP_N=<span style={{ fontFamily: C.mono }}>{state.pt_top_n}</span>
          </span>
          <span style={{ color: C.text4 }}>·</span>
          <span style={{ color: state.l4_auto_enabled ? C.warn : C.text3 }}>
            L4={state.l4_auto_enabled ? "AUTO" : "STAGED"}
          </span>
          {state.dingtalk_enabled && (
            <>
              <span style={{ color: C.text4 }}>·</span>
              <span style={{ color: C.info }}>钉钉 ON</span>
            </>
          )}
        </>
      )}

      {error && (
        <span style={{ color: C.warn, marginLeft: "auto" }}>
          env-state 加载失败: {error}
        </span>
      )}

      {!state && !error && (
        <span style={{ color: C.text4, marginLeft: "auto" }}>加载中…</span>
      )}
    </div>
  );
}
