import React from "react";

export default function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background:
          "radial-gradient(circle at 20% 10%, rgba(31,59,46,0.08), transparent 50%), radial-gradient(circle at 85% 90%, rgba(107,74,36,0.08), transparent 55%), var(--cream)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 16px",
        fontFamily: "var(--body)",
        color: "var(--ink)",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 460,
          background: "var(--paper)",
          border: "1px solid var(--cream-edge)",
          borderRadius: "var(--r-lg)",
          boxShadow: "var(--shadow-card)",
          padding: "34px 34px 28px",
        }}
      >
        <div style={{ marginBottom: 22 }}>
          <div
            style={{
              fontSize: 11,
              letterSpacing: 2,
              color: "var(--forest)",
              textTransform: "uppercase",
              fontWeight: 600,
              marginBottom: 6,
            }}
          >
            BridgeMedAI
          </div>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--display)",
              fontWeight: 500,
              fontSize: 26,
              color: "var(--ink)",
              letterSpacing: -0.2,
            }}
          >
            {title}
          </h1>
          {subtitle && (
            <p style={{ margin: "8px 0 0", color: "var(--ink-muted)", fontSize: 14, lineHeight: 1.5 }}>
              {subtitle}
            </p>
          )}
        </div>
        {children}
        {footer && (
          <div
            style={{
              marginTop: 22,
              paddingTop: 18,
              borderTop: "1px solid var(--cream-edge)",
              fontSize: 13,
              color: "var(--ink-muted)",
              textAlign: "center",
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export const field = {
  label: {
    display: "block",
    fontSize: 12,
    fontWeight: 600,
    color: "var(--ink)",
    letterSpacing: 0.3,
    marginBottom: 6,
    textTransform: "uppercase",
  },
  input: {
    width: "100%",
    boxSizing: "border-box",
    padding: "11px 12px",
    fontSize: 14,
    fontFamily: "var(--body)",
    color: "var(--ink)",
    background: "var(--paper)",
    border: "1px solid var(--cream-edge)",
    borderRadius: 10,
    outline: "none",
    transition: "border-color 0.15s",
  },
  group: { marginBottom: 14 },
  helper: { fontSize: 12, color: "var(--ink-muted)", marginTop: 6 },
  error: {
    marginTop: 12,
    padding: "10px 12px",
    borderRadius: 10,
    background: "rgba(196,85,85,0.08)",
    border: "1px solid rgba(196,85,85,0.25)",
    color: "#8b2e2e",
    fontSize: 13,
  },
  success: {
    marginTop: 12,
    padding: "10px 12px",
    borderRadius: 10,
    background: "rgba(31,59,46,0.06)",
    border: "1px solid rgba(31,59,46,0.2)",
    color: "var(--forest)",
    fontSize: 13,
  },
  primaryBtn: {
    width: "100%",
    marginTop: 6,
    padding: "12px 14px",
    fontSize: 14,
    fontWeight: 600,
    letterSpacing: 0.2,
    color: "var(--paper)",
    background: "var(--forest)",
    border: "none",
    borderRadius: 12,
    cursor: "pointer",
    fontFamily: "var(--body)",
  },
  ghostBtn: {
    width: "100%",
    marginTop: 10,
    padding: "10px 14px",
    fontSize: 13,
    color: "var(--forest)",
    background: "transparent",
    border: "1px solid var(--cream-edge)",
    borderRadius: 12,
    cursor: "pointer",
    fontFamily: "var(--body)",
  },
};
