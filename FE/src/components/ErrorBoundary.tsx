import React, { Component } from "react";

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100vh",
            gap: 20,
            padding: 24,
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 48 }}>⚠️</div>
          <h1 style={{ fontSize: 24, fontWeight: 800, margin: 0 }}>Something went wrong</h1>
          <p style={{ fontSize: 14, color: "var(--color-text-secondary)", maxWidth: 480, margin: 0 }}>
            An unexpected error occurred while rendering this page. Please try reloading.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              border: "none",
              background: "var(--color-fill-solid)",
              color: "var(--color-fill-solid-fg)",
              font: "inherit",
              fontSize: 14,
              fontWeight: 700,
              padding: "10px 24px",
              borderRadius: "var(--radius-lg)",
              cursor: "pointer",
            }}
          >
            Reload
          </button>

          <details style={{ marginTop: 24, maxWidth: 600, textAlign: "left" }}>
            <summary style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-tertiary)", cursor: "pointer" }}>
              Error details
            </summary>
            <pre
              style={{
                marginTop: 8,
                padding: 12,
                background: "var(--color-neutral-100)",
                borderRadius: "var(--radius-md)",
                fontSize: 12,
                color: "var(--color-error-700)",
                overflow: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {this.state.error?.message ?? "Unknown error"}
            </pre>
          </details>
        </div>
      );
    }

    return this.props.children;
  }
}
