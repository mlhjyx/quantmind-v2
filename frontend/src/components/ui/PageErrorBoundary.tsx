import { Component, type ErrorInfo, type ReactNode } from "react";
import { C } from "@/theme";

interface Props { children: ReactNode; }
interface State { error: Error | null; }

export class PageErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[PageErrorBoundary]", error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex flex-col items-center justify-center h-full min-h-64 px-6 text-center">
        <div className="mb-4 text-4xl">⚠️</div>
        <div style={{ fontSize: 16, fontWeight: 600, color: C.text1, marginBottom: 8 }}>
          页面渲染出错
        </div>
        <div
          className="mb-6 px-4 py-2 rounded-lg font-mono text-xs max-w-lg overflow-auto text-left"
          style={{ background: C.bg2, color: C.down, maxHeight: 120 }}
        >
          {error.message}
        </div>
        <div className="flex gap-3">
          <button
            onClick={this.reset}
            className="px-4 py-2 rounded-lg text-sm font-medium"
            style={{ background: C.accent, color: "#fff" }}
          >
            重新加载
          </button>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg text-sm"
            style={{ background: C.bg2, color: C.text2 }}
          >
            刷新页面
          </button>
        </div>
      </div>
    );
  }
}
