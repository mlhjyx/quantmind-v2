import React from "react";
import { C, Glass } from "@/theme";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  glass?: boolean;
}

export function Card({ children, className = "", style = {}, glass = false }: CardProps) {
  const base = glass ? Glass.card : { background: C.bg1, border: `1px solid ${C.border}` };
  return (
    <div className={`rounded-xl ${className}`} style={{ ...base, ...style }}>
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: string;
  titleEn?: string;
  right?: React.ReactNode;
}

export function CardHeader({ title, titleEn, right }: CardHeaderProps) {
  return (
    <div
      className="flex items-center justify-between px-4 py-2 shrink-0"
      style={{ borderBottom: `1px solid ${C.border}` }}
    >
      <span style={{ fontSize: 13, fontWeight: 600, color: C.text1 }}>
        {title}{" "}
        {titleEn && (
          <span style={{ color: C.text4, fontWeight: 400, fontSize: 11 }}>{titleEn}</span>
        )}
      </span>
      {right}
    </div>
  );
}
