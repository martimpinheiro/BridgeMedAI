import { useCallback, useEffect, useState } from "react";

/**
 * useAsyncList — pequeno hook para listar via API com loading/error/reload.
 *
 * - loader: function async que devolve um array
 * - deps: array de dependências que dispara reload quando muda
 *
 * Auto-refresh em `window focus` (silencioso, sem flicker de "A carregar"
 * — atualiza dados em background quando voltas à tab, sem mostrar spinner).
 */
export default function useAsyncList(loader, deps = []) {
  const [state, setState] = useState({ loading: true, error: "", items: [] });

  // Reload normal (com loading spinner) — usado no mount inicial e no
  // botão Recarregar manual
  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const items = await loader();
      setState({ loading: false, error: "", items: items || [] });
    } catch (err) {
      setState({
        loading: false,
        error: err?.message || "Erro ao carregar.",
        items: [],
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Reload silencioso (sem mudar loading) — usado em focus
  const reloadSilent = useCallback(async () => {
    try {
      const items = await loader();
      setState((s) => ({ ...s, items: items || [], error: "" }));
    } catch (_err) {
      // ignora; mantém dados antigos visíveis
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => { reload(); }, [reload]);

  // Refresh silencioso quando o user volta à tab
  useEffect(() => {
    const onFocus = () => reloadSilent();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reloadSilent]);

  return { ...state, reload };
}
