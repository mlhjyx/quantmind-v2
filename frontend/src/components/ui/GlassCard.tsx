import type { ReactNode } from "react";

type GlassCardVariant = "default" | "glow" | "clickable" | "selected";

interface GlassCardProps {
  children: ReactNode;
  variant?: GlassCardVariant;
  className?: string;
  onClick?: () => void;
  padding?: "sm" | "md" | "lg";
}

const paddingMap = {
  sm: "p-3",
  md: "p-4",
  lg: "p-5",
};

const variantMap: Record<GlassCardVariant, string> = {
  default: "border-white/10",
  glow: "border-blue-400/20 shadow-[0_0_20px_rgba(96,165,250,0.15)]",
  clickable:
    "border-white/10 cursor-pointer hover:border-blue-400/40 hover:shadow-[0_0_16px_rgba(96,165,250,0.2)] transition-all duration-200",
  selected:
    "border-blue-500/60 shadow-[0_0_0_1px_rgba(96,165,250,0.4)] border-l-4 border-l-blue-500",
};

export function GlassCard({
  children,
  variant = "default",
  className = "",
  onClick,
  padding = "md",
}: GlassCardProps) {
  return (
    <div
      className={[
        "rounded-2xl border backdrop-blur-xl",
        "bg-[rgba(15,20,45,0.65)]",
        "shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]",
        paddingMap[padding],
        variantMap[variant],
        className,
      ].join(" ")}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  );
}
