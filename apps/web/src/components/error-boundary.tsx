"use client";

import { Component } from "react";
import Link from "next/link";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

/**
 * Client error boundary for the root layout.
 *
 * Previously the fallback was a dead-end: "Something went wrong" with
 * a Try again button that just re-rendered the same children and,
 * if the error was deterministic, crashed again immediately. Users had
 * to hand-edit the URL bar to escape.
 *
 * Resolves UX_REVIEW.md §4.4: the fallback now offers a Go to
 * dashboard escape hatch alongside Try again, announces itself to
 * screen readers (role=alert already in place from Phase 1), and in
 * development surfaces the error message and stack so contributors
 * can debug without opening devtools.
 *
 * TODO(phase-6): wire Sentry.captureException once the Sentry MCP
 * integration is enabled for the project.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({ error, errorInfo: info });
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  private reset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const isDev = process.env.NODE_ENV !== "production";
      const { error, errorInfo } = this.state;

      return (
        <div
          role="alert"
          className="max-w-2xl mx-auto px-4 py-16 text-center"
        >
          <h2 className="text-xl font-semibold mb-2">Something went wrong</h2>
          <p className="text-gray-600 mb-6">
            An unexpected error occurred. You can try again, or head back to
            the dashboard.
          </p>
          <div className="flex flex-col sm:flex-row gap-2 justify-center mb-6">
            <button
              type="button"
              onClick={this.reset}
              className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
            >
              Try again
            </button>
            <Link
              href="/dashboard"
              onClick={this.reset}
              className="px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50"
            >
              Go to dashboard
            </Link>
          </div>

          {isDev && error && (
            <details className="text-left bg-gray-50 border rounded p-4 mt-6">
              <summary className="cursor-pointer text-sm font-medium text-gray-700">
                Error details (dev only)
              </summary>
              <p className="mt-2 text-xs font-mono text-red-700 break-all">
                {error.message}
              </p>
              {error.stack && (
                <pre className="mt-2 text-xs font-mono text-gray-600 whitespace-pre-wrap overflow-x-auto">
                  {error.stack}
                </pre>
              )}
              {errorInfo?.componentStack && (
                <pre className="mt-2 text-xs font-mono text-gray-500 whitespace-pre-wrap overflow-x-auto">
                  {errorInfo.componentStack}
                </pre>
              )}
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
