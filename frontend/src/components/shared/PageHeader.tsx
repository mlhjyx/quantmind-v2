import React from "react";
import { C } from "@/theme";

interface PageHeaderProps {
  title: string;
  titleEn: string;
  right?: React.ReactNode;
  /** @deprecated Use `right` prop instead */
  children?: React.ReactNode;
}

export function PageHeader({ title, titleEn, right, children }: PageHeaderProps) {
  const rightContent = right ?? children;
  return (
    <div className="flex items-center justify-between px-5 py-3 shrink-0">
      <div className="flex items-center gap-3">
        <h1 style={{ fontSize: 18, fontWeight: 700, color: C.text1, margin: 0 }}>{title}</h1>
        <span style={{ fontSize: 12, color: C.text4 }}>{titleEn}</span>
      </div>
      {rightContent && (
        <div className="flex items-center gap-2">{rightContent}</div>
      )}
    </div>
  );
}
