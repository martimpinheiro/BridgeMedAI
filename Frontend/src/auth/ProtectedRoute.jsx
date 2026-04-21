import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext.jsx";

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

  return children;
}

export function defaultRouteFor(user) {
  if (!user) return "/login";
  if (user.role === "admin") return "/admin";
  if (user.role === "specialist" && user.status === "pending") return "/specialist/pending";
  if (user.role === "specialist" && user.status === "rejected") return "/specialist/rejected";
  return "/app";
}
