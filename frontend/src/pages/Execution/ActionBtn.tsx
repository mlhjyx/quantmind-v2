/**
 * ActionBtn — Reusable action button for the Execution control panel.
 * Extracted from Execution.tsx for maintainability.
 */
import { C } from "@/theme";

export function ActionBtn({
  label,
  color,
  disabled,
  loading,
  onClick,
}: {
  label: string;
  color?: string;
  disabled?: boolean;
  loading?: boolean;
  onClick: () => void;
}) {
  const c = color ?? C.accent;
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className="w-full rounded-lg py-2 text-center cursor-pointer transition-opacity"
      style={{
        fontSize: 12,
        fontWeight: 600,
        background: disabled ? C.bg3 : `${c}18`,
        color: disabled ? C.text4 : c,
        border: `1px solid ${disabled ? C.border : c}30`,
        opacity: loading ? 0.6 : 1,
      }}
    >
      {loading ? "执行中..." : label}
    </button>
  );
}
