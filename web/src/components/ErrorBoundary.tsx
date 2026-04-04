import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo });
    console.error('[ErrorBoundary]', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div style={{
          padding: '24px',
          margin: '24px',
          background: '#1a0000',
          border: '1px solid #ff0000',
          borderRadius: '8px',
          color: '#ff6b6b',
          fontFamily: 'monospace',
          fontSize: '13px',
        }}>
          <h2 style={{ color: '#ff4444', margin: '0 0 12px 0', fontSize: '16px' }}>
            Something went wrong
          </h2>
          <p style={{ color: '#ffaaaa', margin: '0 0 8px 0' }}>
            {this.state.error?.message}
          </p>
          <pre style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: '300px',
            overflow: 'auto',
            background: '#0d0000',
            padding: '12px',
            borderRadius: '4px',
            margin: '8px 0 0 0',
          }}>
            {this.state.error?.stack}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '16px',
              padding: '8px 16px',
              background: '#333',
              color: '#fff',
              border: '1px solid #666',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Reload Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
