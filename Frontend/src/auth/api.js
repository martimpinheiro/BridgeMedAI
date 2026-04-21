import { DEFAULT_API_BASE_URL } from "./AuthContext.jsx";

async function parseResponse(res) {
  const contentType = res.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await res.json()
    : await res.text();
  if (!res.ok) {
    const detail = typeof body === "object" && body?.detail
      ? body.detail
      : typeof body === "string" && body
      ? body
      : "Pedido falhou.";
    throw new Error(String(detail));
  }
  return body;
}

export async function apiJson(path, { method = "GET", body, token } = {}) {
  const res = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return parseResponse(res);
}

export async function apiForm(path, { method = "POST", formData, token } = {}) {
  const res = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    method,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  return parseResponse(res);
}

export async function apiDownload(path, { token, filename } = {}) {
  const res = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Erro ao descarregar ficheiro.");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "documento";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
