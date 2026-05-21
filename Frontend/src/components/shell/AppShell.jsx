import React, { useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate, Outlet } from "react-router-dom";
import "./shell.css";
import { useAuth } from "../../auth/AuthContext.jsx";
import { IconBell, IconLogout, IconLeaf } from "../ui/Icons.jsx";

const ROLE_LABEL = {
  admin: "Administração",
  specialist: "Especialista",
  user: "Cliente",
};

/* ---------------------------------------------------------------------- *
 * AppShell — wrapper genérico usado por todos os layouts (admin/spec/user)
 * Recebe `navSections` e `roleLabel` props.
 *
 * navSections shape:
 *   [{ heading: 'Seção', items: [{ to, label, icon, badge }] }]
 * ---------------------------------------------------------------------- */
export default function AppShell({ role, navSections = [], pageTitle }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const initials = useMemo(() => {
    if (!user?.full_name) return "??";
    return user.full_name
      .split(/\s+/)
      .map((p) => p.charAt(0))
      .slice(0, 2)
      .join("")
      .toUpperCase();
  }, [user]);

  const currentTitle = useMemo(() => {
    if (pageTitle) return pageTitle;
    // tenta encontrar match no nav
    for (const section of navSections) {
      for (const item of section.items || []) {
        if (location.pathname.startsWith(item.to)) return item.label;
      }
    }
    return "";
  }, [pageTitle, navSections, location.pathname]);

  const handleLogout = () => {
    logout?.();
    navigate("/login", { replace: true });
  };

  return (
    <div className="bmshell" data-role={role}>
      <aside className="bmshell__sidebar" aria-label="Navegação principal">
        <div className="bmshell__brand">
          <div className="bmshell__brand-eyebrow">BridgeMed · AI</div>
          <div className="bmshell__brand-name">
            Bridge<em>Med</em>AI
          </div>
          <div className="bmshell__brand-role">
            <IconLeaf size={11} />
            {ROLE_LABEL[role] || role}
          </div>
        </div>

        <nav className="bmshell__nav">
          {navSections.map((section, sIdx) => (
            <React.Fragment key={sIdx}>
              {section.heading && (
                <div className="bmshell__nav-section">{section.heading}</div>
              )}
              {(section.items || []).map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    "bmshell__nav-item" +
                    (isActive ? " bmshell__nav-item--active" : "")
                  }
                >
                  {item.icon && (
                    <span className="bmshell__nav-icon">{item.icon}</span>
                  )}
                  <span>{item.label}</span>
                  {item.badge ? (
                    <span className="bmshell__nav-badge">{item.badge}</span>
                  ) : null}
                </NavLink>
              ))}
            </React.Fragment>
          ))}
        </nav>

        <div className="bmshell__user">
          <div className="bmshell__avatar" title={user?.full_name || ""}>
            {initials}
          </div>
          <div className="bmshell__user-info">
            <div className="bmshell__user-name">{user?.full_name || "—"}</div>
            <div className="bmshell__user-meta">
              {ROLE_LABEL[user?.role] || user?.role || ""}
            </div>
          </div>
          <button
            type="button"
            className="bmshell__logout"
            onClick={handleLogout}
            title="Sair"
            aria-label="Terminar sessão"
          >
            <IconLogout size={16} />
          </button>
        </div>
      </aside>

      <main className="bmshell__main">
        <div className="bmshell__topbar">
          <div className="bmshell__topbar-left">
            <span className="bmshell__topbar-title">{currentTitle}</span>
          </div>
          <div className="bmshell__topbar-right">
            <button
              type="button"
              className="bmshell__bell"
              title="Notificações"
              aria-label="Notificações"
            >
              <IconBell size={14} />
              Notificações
            </button>
          </div>
        </div>

        <div className="bmshell__content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
