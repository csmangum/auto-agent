import { Component, createElement, type ErrorInfo, type ReactNode } from 'react';
import { captureException } from '@sentry/react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  retryKey: number;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, retryKey: 0 };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('ErrorBoundary caught:', error, errorInfo);
    captureException(error, {
      extra: {
        componentStack: errorInfo.componentStack,
        message: error.message,
      },
    });
  }

  handleRetry = (): void => {
    this.setState((prev) => ({ hasError: false, error: null, retryKey: prev.retryKey + 1 }));
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="flex flex-col items-center justify-center min-h-[400px] p-8 animate-fade-in">
          <span className="text-5xl mb-4 opacity-30">💥</span>
          <h2 className="text-xl font-semibold text-gray-200 mb-2">Something went wrong</h2>
          <p className="text-sm text-gray-400 mb-6 max-w-md text-center">
            An unexpected error occurred. If the problem persists, contact support. Details were
            reported automatically when error tracking is enabled.
          </p>
          <button
            type="button"
            onClick={this.handleRetry}
            className="px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-500 text-sm font-medium transition-all active:scale-[0.98]"
          >
            Try again
          </button>
        </div>
      );
    }
    return createElement('div', { key: this.state.retryKey }, this.props.children);
  }
}
