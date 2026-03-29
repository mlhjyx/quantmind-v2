interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}

/** Full-page error state for failed data loads */
export function ErrorBanner({
  message,
  onRetry,
  onDismiss,
  className = "",
}: ErrorBannerProps) {
  return (
    <div
      className={[
        "flex items-center justify-between gap-3",
        "bg-red-900/30 border border-red-500/30 rounded-xl px-4 py-3",
        className,
      ].join(" ")}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-red-400 shrink-0">⚠</span>
        <span className="text-sm text-red-300 truncate">{message}</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {onRetry && (
          <button
            onClick={onRetry}
            className="text-xs text-red-300 hover:text-red-100 underline transition-colors"
          >
            重试
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-xs text-red-400 hover:text-red-200 transition-colors"
            aria-label="关闭"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

/** Inline error block for card-level failures */
export function InlineError({
  message,
  className = "",
}: {
  message: string;
  className?: string;
}) {
  return (
    <div
      className={[
        "flex flex-col items-center justify-center py-8 text-center",
        className,
      ].join(" ")}
    >
      <span className="text-2xl mb-2">⚠</span>
      <p className="text-sm text-red-400">{message}</p>
    </div>
  );
}
