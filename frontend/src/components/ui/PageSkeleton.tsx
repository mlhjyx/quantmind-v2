interface PageSkeletonProps {
  /** Number of skeleton cards to render (default 4) */
  cards?: number;
  /** Show a header skeleton (default true) */
  header?: boolean;
  className?: string;
}

function SkeletonBlock({ className = "" }: { className?: string }) {
  return (
    <div
      className={["rounded-lg bg-white/[0.06] animate-pulse", className].join(
        " "
      )}
    />
  );
}

export function PageSkeleton({
  cards = 4,
  header = true,
  className = "",
}: PageSkeletonProps) {
  return (
    <div className={["space-y-4", className].join(" ")}>
      {header && (
        <div className="flex items-center justify-between mb-2">
          <div className="space-y-2">
            <SkeletonBlock className="h-7 w-48" />
            <SkeletonBlock className="h-4 w-64" />
          </div>
          <SkeletonBlock className="h-8 w-24 rounded-xl" />
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: cards }).map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-white/10 bg-[rgba(15,20,45,0.65)] p-4 space-y-2"
          >
            <SkeletonBlock className="h-3 w-20" />
            <SkeletonBlock className="h-6 w-28" />
            <SkeletonBlock className="h-3 w-16" />
          </div>
        ))}
      </div>
      <div className="rounded-2xl border border-white/10 bg-[rgba(15,20,45,0.65)] p-4">
        <SkeletonBlock className="h-4 w-32 mb-4" />
        <SkeletonBlock className="h-40 w-full rounded-xl" />
      </div>
    </div>
  );
}

/** Inline skeleton for a single card's content area */
export function CardSkeleton({ rows = 3, className = "" }: { rows?: number; className?: string }) {
  return (
    <div className={["space-y-2 py-2", className].join(" ")}>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonBlock
          key={i}
          className={`h-4 ${i === 0 ? "w-3/4" : i % 2 === 0 ? "w-1/2" : "w-full"}`}
        />
      ))}
    </div>
  );
}
