import React from "react";
import { Navigate, useLocation, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext.jsx";

/**
 * ProtectedRoute — guarda de autenticação + autorização por role.
 *
 * Suporta dois padrões de uso:
 *  1) Wrapper de uma rota única:
 *     <Route element={<ProtectedRoute roles={["admin"]}><AdminPanel/></ProtectedRoute>}/>
 *
 *  2) Wrapper de um grupo de rotas (com nested routes):
 *     <Route element={<ProtectedRoute roles={["admin"]}/>}>
 *       <Route path="/admin/dashboard" element={<AdminDashboard/>}/>
 *       <Route path="/admin/users" element={<AdminUsers/>}/>
 *     </Route>
 */
export default function ProtectedRoute({ roles, requireActive = true, children }) {
  const { user } = useAuth();
  const location = useLocation();

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (roles && !roles.includes(user.role)) {
    return <Navigate to={defaultRouteFor(user)} replace />;
  }

  if (requireActive && user.status !== "active") {
    if (user.role === "specialist" && user.status === "pending") {
      return <Navigate to="/specialist/pending" replace />;
    }
    if (user.role === "specialist" && user.status === "rejected") {
      return <Navigate to="/specialist/rejected" replace />;
    }
    return <Navigate to="/login" replace />;
  }

  // Se a rota tem `children` explícitos, renderiza-os; caso contrário usa <Outlet/>
  // para nested routes do react-router.
  return children ? children : <Outlet />;
}

export function defaultRouteFor(user) {
  if (!user) return "/login";
  if (user.role === "admin") return "/admin/dashboard";
  if (user.role === "specialist") {
    if (user.status === "pending") return "/specialist/pending";
    if (user.status === "rejected") return "/specialist/rejected";
    return "/specialist/dashboard";
  }
  return "/user/dashboard";
}
