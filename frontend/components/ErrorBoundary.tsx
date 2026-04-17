"use client";
import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: "" };

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err.message };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center h-40 gap-2 text-bloomberg-muted text-xs">
          <AlertTriangle size={16} className="text-red-400" />
          <p className="text-red-400 font-medium">Something went wrong</p>
          <p className="text-[10px] max-w-xs text-center">{this.state.message}</p>
          <button
            onClick={() => this.setState({ hasError: false, message: "" })}
            className="mt-1 text-[10px] border border-bloomberg-border px-3 py-1 hover:border-bloomberg-gold hover:text-bloomberg-gold"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
