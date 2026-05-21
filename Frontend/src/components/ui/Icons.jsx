/* ---------------------------------------------------------------------------
 * BridgeMedAI — Inline SVG icons
 *
 * Sem dependência de libraries de ícones. Cada ícone é uma function
 * component que aceita `size` e quaisquer props SVG. Stroke usa
 * `currentColor` para herdar do contexto.
 * ------------------------------------------------------------------------- */
import React from "react";

const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

function Svg({ size = 18, children, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      {...base}
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconDashboard = (p) => (
  <Svg {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </Svg>
);

export const IconChat = (p) => (
  <Svg {...p}>
    <path d="M21 12a8 8 0 1 1-3.4-6.5L21 4l-1.1 3.5A8 8 0 0 1 21 12z" />
    <path d="M8 11h6M8 14h4" />
  </Svg>
);

export const IconUsers = (p) => (
  <Svg {...p}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3 19c0-3 2.5-5 6-5s6 2 6 5" />
    <circle cx="17" cy="9" r="2.5" />
    <path d="M14 14.5c2.5.4 4.5 1.9 5 4" />
  </Svg>
);

export const IconShield = (p) => (
  <Svg {...p}>
    <path d="M12 3l8 3v5c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-3z" />
    <path d="M9 12l2 2 4-4" />
  </Svg>
);

export const IconScroll = (p) => (
  <Svg {...p}>
    <path d="M4 5a2 2 0 0 1 2-2h11l3 3v13a2 2 0 0 1-2 2H7" />
    <path d="M4 5v14a2 2 0 0 0 2 2" />
    <path d="M9 8h6M9 12h6M9 16h4" />
  </Svg>
);

export const IconStack = (p) => (
  <Svg {...p}>
    <path d="M12 3l9 4.5L12 12 3 7.5 12 3z" />
    <path d="M3 12l9 4.5L21 12" />
    <path d="M3 16.5L12 21l9-4.5" />
  </Svg>
);

export const IconHistory = (p) => (
  <Svg {...p}>
    <path d="M3 12a9 9 0 1 0 3-6.7" />
    <path d="M3 4v4h4" />
    <path d="M12 8v5l3 2" />
  </Svg>
);

export const IconInbox = (p) => (
  <Svg {...p}>
    <path d="M3 13l3-8h12l3 8" />
    <path d="M3 13v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6" />
    <path d="M3 13h5l1.5 2h5L16 13h5" />
  </Svg>
);

export const IconCheckList = (p) => (
  <Svg {...p}>
    <path d="M9 5l1.5 1.5L13 4" />
    <path d="M9 12l1.5 1.5L13 11" />
    <path d="M9 19l1.5 1.5L13 18" />
    <path d="M17 5h4M17 12h4M17 19h4" />
  </Svg>
);

export const IconGear = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c0 .7.4 1.3 1 1.5H21a2 2 0 0 1 0 4h-.1c-.6 0-1.2.4-1.5 1z" />
  </Svg>
);

export const IconBell = (p) => (
  <Svg {...p}>
    <path d="M6 8a6 6 0 1 1 12 0v4l1.5 3h-15L6 12V8z" />
    <path d="M10 19a2 2 0 0 0 4 0" />
  </Svg>
);

export const IconLogout = (p) => (
  <Svg {...p}>
    <path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h3" />
    <path d="M16 17l5-5-5-5" />
    <path d="M21 12H9" />
  </Svg>
);

export const IconChevronDown = (p) => (
  <Svg {...p}>
    <polyline points="6 9 12 15 18 9" />
  </Svg>
);

export const IconChevronRight = (p) => (
  <Svg {...p}>
    <polyline points="9 6 15 12 9 18" />
  </Svg>
);

export const IconSparkle = (p) => (
  <Svg {...p}>
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
    <circle cx="12" cy="12" r="2" />
  </Svg>
);

export const IconArrowRight = (p) => (
  <Svg {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
);

export const IconActivity = (p) => (
  <Svg {...p}>
    <polyline points="3 12 7 12 10 5 14 19 17 12 21 12" />
  </Svg>
);

export const IconClock = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <polyline points="12 7 12 12 15 14" />
  </Svg>
);

export const IconCheck = (p) => (
  <Svg {...p}>
    <polyline points="20 6 9 17 4 12" />
  </Svg>
);

export const IconX = (p) => (
  <Svg {...p}>
    <line x1="6" y1="6" x2="18" y2="18" />
    <line x1="6" y1="18" x2="18" y2="6" />
  </Svg>
);

export const IconAlert = (p) => (
  <Svg {...p}>
    <path d="M12 2L2 21h20L12 2z" />
    <line x1="12" y1="9" x2="12" y2="14" />
    <circle cx="12" cy="17.5" r="0.6" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconLeaf = (p) => (
  <Svg {...p}>
    <path d="M21 3c0 8-4 14-13 14a4 4 0 0 1-4-4C4 7 11 3 21 3z" />
    <path d="M4 21c0-6 4-10 10-12" />
  </Svg>
);
