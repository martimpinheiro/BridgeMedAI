import React from "react";
import "./ui.css";

/* ------------------------------------------------------------------- *
 * PageHeader — usado no topo de cada página interna (dashboards e listas)
 * ------------------------------------------------------------------- */
export function PageHeader({ crumb, title, sub, actions }) {
  return (
    <header className="bmui-page-header">
      <div className="bmui-page-header__main">
        {crumb && <div className="bmui-page-header__crumb">{crumb}</div>}
        <h1 className="bmui-page-header__title">{title}</h1>
        {sub && <p className="bmui-page-header__sub">{sub}</p>}
      </div>
      {actions && <div className="bmui-page-header__actions">{actions}</div>}
    </header>
  );
}

/* ------------------------------------------------------------------- *
 * Button (link OU button)
 * ------------------------------------------------------------------- */
export function Button({
  children,
  variant = "primary",
  size = "default",
  as,
  ...rest
}) {
  const Tag = as || "button";
  const classes = ["bmui-btn"];
  if (variant === "ghost") classes.push("bmui-btn--ghost");
  if (variant === "danger") classes.push("bmui-btn--danger");
  if (size === "small") classes.push("bmui-btn--small");
  return (
    <Tag className={classes.join(" ")} {...rest}>
      {children}
    </Tag>
  );
}

/* ------------------------------------------------------------------- *
 * Card — wrapper genérico
 * ------------------------------------------------------------------- */
export function Card({ title, subtitle, children, variant, className, ...rest }) {
  const cls = ["bmui-card"];
  if (variant === "quiet") cls.push("bmui-card--quiet");
  if (variant === "accent") cls.push("bmui-card--accent");
  if (className) cls.push(className);
  return (
    <section className={cls.join(" ")} {...rest}>
      {title && <h3 className="bmui-card__title">{title}</h3>}
      {subtitle && <p className="bmui-card__sub">{subtitle}</p>}
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------- *
 * KPICard — número grande + label + delta opcional
 * ------------------------------------------------------------------- */
export function KPICard({ label, value, unit, delta, deltaDir, icon }) {
  const deltaClass =
    deltaDir === "up"
      ? "bmui-kpi__delta bmui-kpi__delta--up"
      : deltaDir === "down"
      ? "bmui-kpi__delta bmui-kpi__delta--down"
      : "bmui-kpi__delta";
  return (
    <article className="bmui-kpi">
      <div className="bmui-kpi__head">
        <div className="bmui-kpi__label">{label}</div>
        {icon && <div className="bmui-kpi__icon">{icon}</div>}
      </div>
      <div className="bmui-kpi__value">
        {value}
        {unit && <sub>{unit}</sub>}
      </div>
      {delta && <div className={deltaClass}>{delta}</div>}
    </article>
  );
}

/* ------------------------------------------------------------------- *
 * StatusPill — badge editorial
 * ------------------------------------------------------------------- */
export function StatusPill({ children, tone = "muted" }) {
  return <span className={`bmui-pill bmui-pill--${tone}`}>{children}</span>;
}

/* ------------------------------------------------------------------- *
 * SectionHeading
 * ------------------------------------------------------------------- */
export function SectionHeading({ children }) {
  return <h2 className="bmui-section-h">{children}</h2>;
}

/* ------------------------------------------------------------------- *
 * EmptyState
 * ------------------------------------------------------------------- */
export function EmptyState({ title, message, action }) {
  return (
    <div className="bmui-empty">
      {title && <h3 className="bmui-empty__title">{title}</h3>}
      {message && <p className="bmui-empty__msg">{message}</p>}
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------- *
 * Spinner
 * ------------------------------------------------------------------- */
export function Spinner({ label = "A carregar" }) {
  return <span className="bmui-spinner">{label}</span>;
}

/* ------------------------------------------------------------------- *
 * Grid
 * ------------------------------------------------------------------- */
export function Grid({ cols = 3, children, style }) {
  const cls = `bmui-grid bmui-grid--${cols}`;
  return (
    <div className={cls} style={style}>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------- *
 * Hero (usado nas dashboards de user)
 * ------------------------------------------------------------------- */
export function Hero({ eyebrow, title, lead, cta }) {
  return (
    <section className="bmui-hero">
      {eyebrow && <div className="bmui-hero__eyebrow">{eyebrow}</div>}
      {title && <h1 className="bmui-hero__title">{title}</h1>}
      {lead && <p className="bmui-hero__lead">{lead}</p>}
      {cta}
    </section>
  );
}

/* ------------------------------------------------------------------- *
 * List + row
 * ------------------------------------------------------------------- */
export function List({ children }) {
  return <ul className="bmui-list">{children}</ul>;
}

export function ListRow({ primary, meta, actions }) {
  return (
    <li className="bmui-list__row">
      <div>
        <div className="bmui-list__primary">{primary}</div>
        {meta && <div className="bmui-list__meta">{meta}</div>}
      </div>
      {actions && <div className="bmui-list__actions">{actions}</div>}
    </li>
  );
}
