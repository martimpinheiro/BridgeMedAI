import React from "react";
import AppShell from "../components/shell/AppShell.jsx";
import {
  IconDashboard,
  IconUsers,
  IconShield,
  IconCheckList,
  IconScroll,
  IconGear,
} from "../components/ui/Icons.jsx";

const NAV = [
  {
    heading: "Visão geral",
    items: [
      { to: "/admin/dashboard", label: "Dashboard", icon: <IconDashboard size={16} /> },
    ],
  },
  {
    heading: "Pessoas",
    items: [
      { to: "/admin/specialists", label: "Especialistas", icon: <IconShield size={16} /> },
      { to: "/admin/users", label: "Utilizadores", icon: <IconUsers size={16} /> },
      { to: "/admin/invites", label: "Convites de admin", icon: <IconCheckList size={16} /> },
    ],
  },
  {
    heading: "Qualidade",
    items: [
      { to: "/admin/matrix", label: "Matriz regulatória", icon: <IconScroll size={16} /> },
      { to: "/admin/logs", label: "Logs & métricas", icon: <IconDashboard size={16} /> },
    ],
  },
  {
    heading: "Sistema",
    items: [
      { to: "/admin/settings", label: "Configurações", icon: <IconGear size={16} /> },
    ],
  },
];

export default function AdminLayout() {
  return <AppShell role="admin" navSections={NAV} />;
}
