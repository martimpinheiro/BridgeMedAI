import React, { useEffect, useState } from "react";
import "./matrix.css";
import { Button, StatusPill } from "../ui/index.jsx";
import { IconCheck } from "../ui/Icons.jsx";

const RESULT_OPTIONS = [
  { value: "OK", label: "OK", tone: "ok" },
  { value: "PARCIAL", label: "Parcial", tone: "warn" },
  { value: "NOK", label: "NOK", tone: "bad" },
];

const SEVERITY_OPTIONS = [
  { value: "", label: "—" },
  { value: "baixa", label: "Baixa" },
  { value: "média", label: "Média" },
  { value: "alta", label: "Alta" },
];

const ERROR_TYPE_OPTIONS = [
  { value: "", label: "—" },
  { value: "E1", label: "E1 · Alucinação" },
  { value: "E2", label: "E2 · Citação errada" },
  { value: "E3", label: "E3 · Classificação errada" },
  { value: "E4", label: "E4 · Resposta incompleta" },
  { value: "E5", label: "E5 · Formato errado" },
  { value: "E6", label: "E6 · Falha técnica" },
  { value: "E7", label: "E7 · Outro" },
];

/**
 * MatrixReviewForm — form embed dentro do detalhe de uma entrada da matriz.
 * Funciona tanto para admin como para especialista; o caller passa `onSubmit`
 * que faz o PATCH ao endpoint apropriado (/admin/traceability/{id} ou
 * /specialist/traceability/{id}).
 */
export default function MatrixReviewForm({ entry, onSubmit, busy }) {
  const [result, setResult] = useState(entry.result || "");
  const [severity, setSeverity] = useState(entry.severity || "");
  const [errorType, setErrorType] = useState(entry.error_type || "");
  // Tira o prefixo [reviewer:...] das notas existentes para edição limpa
  const cleanNotes = (entry.reviewer_notes || "").replace(/^\[reviewer:[a-f0-9]{4,}\]\s*/i, "");
  const [notes, setNotes] = useState(cleanNotes);
  const [localError, setLocalError] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    setResult(entry.result || "");
    setSeverity(entry.severity || "");
    setErrorType(entry.error_type || "");
    setNotes((entry.reviewer_notes || "").replace(/^\[reviewer:[a-f0-9]{4,}\]\s*/i, ""));
    setJustSaved(false);
  }, [entry.id, entry.result, entry.severity, entry.error_type, entry.reviewer_notes]);

  const handleSubmit = async (overrideResult) => {
    setLocalError("");
    setJustSaved(false);
    const payload = {
      result: overrideResult ?? (result || null),
      severity: severity || null,
      error_type: errorType || null,
      reviewer_notes: notes.trim() || null,
    };
    if (!payload.result) {
      setLocalError("Indica o resultado (OK, Parcial ou NOK).");
      return;
    }
    try {
      await onSubmit(entry.id, payload);
      setJustSaved(true);
    } catch (err) {
      setLocalError(err?.message || "Erro ao guardar revisão.");
    }
  };

  const reviewerTag = (entry.reviewer_notes || "").match(/^\[reviewer:([a-f0-9]+)\]/i);

  return (
    <div className="matrix-review">
      <div className="matrix-review__head">
        <span className="matrix-review__label">Revisão</span>
        {reviewerTag && (
          <span className="matrix-review__reviewer">
            revisto por <code>{reviewerTag[1]}</code>
          </span>
        )}
      </div>

      <div className="matrix-review__grid">
        <Field label="Resultado">
          <div className="matrix-review__chips">
            {RESULT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`matrix-review__chip ${result === opt.value ? `is-${opt.tone} is-active` : ""}`}
                onClick={() => setResult(opt.value)}
                disabled={busy}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Severidade">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} disabled={busy} className="matrix-review__select">
            {SEVERITY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>

        <Field label="Tipo de erro">
          <select value={errorType} onChange={(e) => setErrorType(e.target.value)} disabled={busy} className="matrix-review__select">
            {ERROR_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
      </div>

      <Field label="Notas (o que melhorar, observações)">
        <textarea
          className="matrix-review__textarea"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Ex: 'Resposta correta mas falta citar o artigo 87 do MDR.' ou 'A classificação está errada — devia ser IIb pela Rule 11.'"
          rows={4}
          disabled={busy}
        />
      </Field>

      {localError && <div className="matrix-review__error">{localError}</div>}

      <div className="matrix-review__actions">
        <Button onClick={() => handleSubmit()} disabled={busy}>
          {busy ? "A guardar…" : <><IconCheck size={12} /> Guardar revisão</>}
        </Button>
        <Button variant="ghost" size="small" onClick={() => handleSubmit("OK")} disabled={busy}>
          Marcar como OK
        </Button>
        <Button variant="ghost" size="small" onClick={() => handleSubmit("PARCIAL")} disabled={busy}>
          Marcar como Parcial
        </Button>
        <Button variant="danger" size="small" onClick={() => handleSubmit("NOK")} disabled={busy}>
          Marcar como NOK
        </Button>
        {justSaved && (
          <span className="matrix-review__saved">
            <IconCheck size={12} /> Guardado
          </span>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div className="matrix-review__field">
      <label className="matrix-review__field-label">{label}</label>
      {children}
    </div>
  );
}
