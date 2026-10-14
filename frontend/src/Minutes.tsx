import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { addMinuteDraftRow, analyzeMinutes, createProposalFromMinuteDraft, deleteMinuteDraftRow,
  downloadMinuteDraftXlsx, editMinutesItem, findJiraAssigneesCached, getMinuteDraft,
  getMinuteTrackingCatalog, getMinutesEnrichment, getMinutesStatus, preflightProposal,
  updateMinuteDraftProjectResponsible, updateMinuteDraftRow, validateMinuteDraft, type MinutesStatus } from "./api";
import type { JiraAssignee, MinuteDraftRow, MinuteExcelDraft, MinutesEnrichment, Proposal, ProposalItem } from "./types";
import { emitOnboardingEvent } from "./onboardingEvents";
import { RadarIA } from "./RadarIA";

function minutesErrorMessage(reason: unknown): string {
  if (!(reason instanceof Error)) return "No fue posible analizar la minuta.";
  const code = (reason as { code?: string }).code;
  switch (code) {
    case "MINUTES_MODEL_TIMEOUT": return "El modelo tardó demasiado en analizar la minuta. Intenta con menos texto.";
    case "MINUTES_MODEL_UNAVAILABLE": return "El modelo local configurado no está disponible.";
    case "MINUTES_INVALID_JSON": return "El modelo respondió, pero no produjo una estructura válida.";
    case "MINUTES_VALIDATION_FAILED": return "La respuesta del modelo no pasó la validación de seguridad.";
    case "MINUTES_CONTEXT_TOO_LARGE": return "La minuta supera el contexto permitido por el modelo. Reduce el texto e inténtalo de nuevo.";
    default: return reason.message;
  }
}

function greetingFor(displayName?: string): string {
  const firstName = displayName?.trim().split(/\s+/)[0];
  return firstName ? `Hola, ${firstName}` : "Hola";
}

export function NewProposal({ token, onCreated, excel, displayName, telegramUrl }: {
  token: string;
  onCreated: (proposal: Proposal) => void;
  excel: ReactNode;
  displayName?: string;
  telegramUrl?: string | null;
}) {
  const [mode, setMode] = useState<"minutes" | "excel">("minutes");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<MinutesStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState<MinuteExcelDraft | null>(null);
  const inFlight = useRef(false);
  const draftRef = useRef<MinuteExcelDraft | null>(null);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    if (mode !== "minutes") return;
    let active = true;
    getMinutesStatus(token).then(value => { if (active) setStatus(value); })
      .catch(reason => { if (active) setError(minutesErrorMessage(reason)); });
    return () => { active = false; };
  }, [token, mode]);
  useEffect(() => { draftRef.current = draft; }, [draft]);
  useEffect(() => { if (draft) emitOnboardingEvent("analysis:completed"); }, [draft]);
  useEffect(() => {
    const stored = localStorage.getItem("minute-excel-draft-id");
    if (!stored) return;
    getMinuteDraft(token, stored).then(value => { draftRef.current = value; setDraft(value); })
      .catch(() => localStorage.removeItem("minute-excel-draft-id"));
  }, [token]);
  async function analyze(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    emitOnboardingEvent("analyze:clicked");
    setLoading(true); setError("");
    try {
      const result = await analyzeMinutes(token, text);
      if (result.draft) {
        draftRef.current = result.draft; setDraft(result.draft);
        localStorage.setItem("minute-excel-draft-id", result.draft.draft_id);
      } else if (result.proposal) onCreated(result.proposal);
    }
    catch (reason) { setError(minutesErrorMessage(reason)); }
    finally { inFlight.current = false; setLoading(false); }
  }
  async function saveRow(candidateId: string, changes: Partial<MinuteDraftRow>) {
    saveQueue.current = saveQueue.current.then(async () => {
      const current = draftRef.current;
      if (!current) return;
      const updated = await updateMinuteDraftRow(token, current.draft_id, candidateId, current.version, changes);
      draftRef.current = updated; setDraft(updated);
    }).catch(reason => setError(reason instanceof Error ? reason.message : "No fue posible guardar los cambios."));
    await saveQueue.current;
  }
  async function saveProjectResponsible(changes: Partial<NonNullable<MinuteExcelDraft["document"]>>) {
    saveQueue.current = saveQueue.current.then(async () => {
      const current = draftRef.current;
      if (!current) return;
      const updated = await updateMinuteDraftProjectResponsible(token, current.draft_id, current.version, changes);
      draftRef.current = updated; setDraft(updated);
    }).catch(reason => setError(reason instanceof Error ? reason.message : "No fue posible guardar el responsable del proyecto."));
    await saveQueue.current;
  }
  if (draft) return <MinuteDraftPreview token={token} draft={draft} setDraft={value => {
    draftRef.current = value; setDraft(value);
  }} onSave={saveRow} onSaveProjectResponsible={saveProjectResponsible} onCreated={proposal => {
    onCreated(proposal);
  }} onReanalyze={() => { localStorage.removeItem("minute-excel-draft-id"); setDraft(null); }} />;
  return <section className="minutes-entry">
    <div className="minutes-workspace">
      <div className="minutes-main-column">
      <header className="minutes-entry-header">
        <span className="eyebrow">Crear actividades</span>
        <h1 className="minutes-welcome-title">{greetingFor(displayName)} <span aria-hidden="true">👋</span></h1>
        <p className="minutes-welcome-subtitle">Convierte tus pendientes<br /><strong>en actividades claras.</strong></p>
        <p className="minutes-welcome-support">Pega una minuta o carga un archivo para empezar. Después revisa, corrige y prepara tus actividades para Jira.</p>
      </header>
        <div className="minutes-switch" role="group" aria-label="Fuente de la propuesta">
          <button data-tour-id="minutes-tab" className={`button ${mode === "minutes" ? "primary" : "secondary"}`} aria-pressed={mode === "minutes"} disabled={loading} onClick={() => { setMode("minutes"); emitOnboardingEvent("minutes:selected"); }}>Pegar minuta</button>
          <button className={`button ${mode === "excel" ? "primary" : "secondary"}`} aria-pressed={mode === "excel"} disabled={loading} onClick={() => setMode("excel")}>Cargar archivo</button>
        </div>
        {mode === "excel" ? excel : <form className="minutes-card" onSubmit={analyze}>
          <label htmlFor="minutes-text">
            <span className="minutes-card-label-title">Pega aquí tu minuta, acuerdos o pendientes</span>
            <span className="minutes-card-label-help">El agente identificará actividades y contexto a partir de tu texto.</span>
          </label>
          <textarea data-tour-id="minutes-input" id="minutes-text" rows={13} value={text} maxLength={status?.max_chars ?? 30000} disabled={loading}
            onChange={event => { setText(event.target.value); if (event.target.value.trim().length >= 40) emitOnboardingEvent("input:minutes"); }} placeholder="Pega aquí tu minuta, acuerdos o pendientes de la reunión…" />
          <div className="minutes-card-meta">
            <small>{text.length.toLocaleString()} / {(status?.max_chars ?? 30000).toLocaleString()} caracteres</small>
            <p>✦ Nada se creará en Jira durante este paso.</p>
          </div>
          {status && status.state !== "READY" && <div className="alert warning" role="status">{status.detail}{status.model && <p>Modelo configurado: {status.model}</p>}</div>}
          {!status && !error && <p role="status">Consultando disponibilidad de IA local…</p>}
          {error && <div className="alert error" role="alert">{error}</div>}
          <button data-tour-id="analyze-minutes" className="button primary" type="submit" disabled={loading || status?.state !== "READY" || text.trim().length < 40}>
            <span className="ai-action-icon" aria-hidden="true">✦</span>
            {loading ? "Analizando minuta..." : "Analizar minuta"}
          </button>
        </form>}
      </div>
      <RadarIA telegramUrl={telegramUrl} />
    </div>
  </section>;
}

function FieldState({ row, field }: { row: MinuteDraftRow; field: string }) {
  const state = row.field_status[field];
  const issue = row.validation_errors.find(value => value.field === field);
  if (state === "EMPTY_ALLOWED") return <small className="draft-field-state neutral">Opcional</small>;
  if (state === "VALID") return <small className="draft-field-state valid">✓ Válido</small>;
  return <small className={`draft-field-state ${state === "INVALID" ? "invalid" : "review"}`}>⚠ {issue?.message ?? "Requiere revisión"}</small>;
}

function normalizeAssigneeQuery(value: string): string {
  return value.trim().toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function ResponsableStatus({ status, row }: { status: NonNullable<MinuteDraftRow["responsable_resolution_status"]>; row: MinuteDraftRow }) {
  if (status === "VALIDATED_JIRA") return <small className="draft-field-state valid">✓ Validado con Jira</small>;
  if (status === "AUTO_RESOLVED") return <small className="draft-field-state valid">✓ Resuelto automáticamente con Jira</small>;
  if (status === "EXPLICIT_MINUTES") return <small className="draft-field-state valid">✓ Responsable explícito en la minuta; pendiente Jira</small>;
  if (status === "RESOLVING") return <small className="draft-field-state neutral">Buscando responsable en Jira…</small>;
  if (status === "MULTIPLE_MATCHES") return <small className="draft-field-state review">⚠ Hay varias coincidencias Jira. Selecciona una.</small>;
  if (status === "NOT_FOUND") return <small className="draft-field-state review">⚠ Responsable no encontrado en Jira. Se conserva el texto.</small>;
  if (status === "UNAVAILABLE") return <small className="draft-field-state review">⚠ Jira no está disponible. Se conserva la edición local.</small>;
  return <FieldState row={row} field="responsable" />;
}

function MinuteDraftTableRow({ row, draft, token, onSave, onDelete, onResponsablePending,
  selected, onSelect, onPrepare, preparing, areaOptions }: {
  row: MinuteDraftRow; draft: MinuteExcelDraft; token: string;
  onSave: (candidateId: string, changes: Partial<MinuteDraftRow>) => Promise<void>;
  onDelete: () => void;
  onResponsablePending: (candidateId: string, pending: boolean) => void;
  selected: boolean; onSelect: (candidateId: string, selected: boolean) => void;
  onPrepare: (candidateIds: string[]) => void; preparing: boolean;
  areaOptions: Array<{ key: string; value: string; label: string }>;
}) {
  const [value, setValue] = useState(row);
  const [assignees, setAssignees] = useState<JiraAssignee[]>([]);
  const [lookup, setLookup] = useState(false);
  const [ignored, setIgnored] = useState<string[]>([]);
  const [resolutionStatus, setResolutionStatus] = useState<NonNullable<MinuteDraftRow["responsable_resolution_status"]>>(row.responsable_resolution_status ?? "UNRESOLVED");
  const [retrySearch, setRetrySearch] = useState(0);
  const lastSearched = useRef("");
  const pendingQuery = useRef(normalizeAssigneeQuery(row.responsable ?? ""));
  const responsibleSaveTimer = useRef<number | undefined>(undefined);
  const onSaveRef = useRef(onSave);
  useEffect(() => { onSaveRef.current = onSave; }, [onSave]);
  useEffect(() => () => window.clearTimeout(responsibleSaveTimer.current), []);
  useEffect(() => setValue(row), [row]);
  useEffect(() => setResolutionStatus(row.responsable_resolution_status ?? "UNRESOLVED"), [row.responsable_resolution_status]);
  const change = (field: keyof MinuteDraftRow, next: string | null) => setValue(current => ({ ...current, [field]: next }));
  const save = (field: keyof MinuteDraftRow) => {
    if (value[field] !== row[field]) void onSave(row.candidate_id, { [field]: value[field] } as Partial<MinuteDraftRow>);
  };
  const query = value.responsable === "Por definir" ? "" : value.responsable?.trim() ?? "";
  useEffect(() => {
    const normalized = normalizeAssigneeQuery(query);
    if (normalized.length < 2 || normalized === "por definir") {
      setResolutionStatus(normalized === normalizeAssigneeQuery(row.responsable ?? "")
        ? row.responsable_resolution_status ?? "UNRESOLVED" : "UNRESOLVED");
      setAssignees([]);
      return;
    }
    if (normalized === normalizeAssigneeQuery(row.responsable ?? "")
      && row.responsable_account_id
      && ["AUTO_RESOLVED", "VALIDATED_JIRA"].includes(row.responsable_resolution_status ?? "")) {
      setResolutionStatus(row.responsable_resolution_status ?? "VALIDATED_JIRA");
      setAssignees([]);
      onResponsablePending(row.candidate_id, false);
      return;
    }
    if (lastSearched.current === normalized) return;
    let active = true;
    onResponsablePending(row.candidate_id, true);
    setResolutionStatus("RESOLVING");
    const timer = window.setTimeout(async () => {
      lastSearched.current = normalized;
      setLookup(true);
      try {
        // Persist the new text and clear a previous account identity before searching.
        await onSaveRef.current(row.candidate_id, { responsable: query, responsable_account_id: null,
          responsable_resolution_status: "RESOLVING" });
        const results = await findJiraAssigneesCached(token, draft.jira_space_key ?? "AT", query);
        if (!active) return;
        const activeResults = results.filter(item => item.active !== false && item.account_id);
        setAssignees(activeResults);
        if (activeResults.length === 1) {
          const selected = activeResults[0];
          const name = selected.display_name ?? query;
          const cleanName = name.toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
          const plausible = cleanName === normalized || cleanName.includes(normalized)
            || normalized.split(/\s+/).every(part => cleanName.includes(part));
          if (plausible) {
            lastSearched.current = cleanName;
            pendingQuery.current = cleanName;
            setValue(current => ({ ...current, responsable: name }));
            setAssignees([]);
            setResolutionStatus("AUTO_RESOLVED");
            await onSaveRef.current(row.candidate_id, { responsable: name, responsable_account_id: selected.account_id,
              responsable_resolution_status: "AUTO_RESOLVED", responsable_lookup_query: query });
            emitOnboardingEvent("responsible:validated", { rowId: row.candidate_id });
            if (pendingQuery.current === cleanName) onResponsablePending(row.candidate_id, false);
            return;
          }
        }
        const ambiguousSingle = activeResults.length === 1 && !(
          (activeResults[0].display_name ?? "").toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").includes(normalized)
          || normalized.split(/\s+/).every(part => (activeResults[0].display_name ?? "").toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").includes(part))
        );
        if (activeResults.length > 1 || ambiguousSingle) {
          setResolutionStatus("MULTIPLE_MATCHES");
          await onSaveRef.current(row.candidate_id, { responsable: query, responsable_account_id: null,
            responsable_resolution_status: "MULTIPLE_MATCHES" });
        } else {
          setResolutionStatus("NOT_FOUND");
          await onSaveRef.current(row.candidate_id, { responsable: query, responsable_account_id: null,
            responsable_resolution_status: "NOT_FOUND" });
        }
      } catch {
        if (active) {
          setResolutionStatus("UNAVAILABLE");
          setAssignees([]);
          await onSaveRef.current(row.candidate_id, { responsable_resolution_status: "UNAVAILABLE" }).catch(() => undefined);
        }
      } finally {
        if (active) setLookup(false);
        if (active && pendingQuery.current === normalized) onResponsablePending(row.candidate_id, false);
      }
    }, 400);
    return () => { active = false; window.clearTimeout(timer); };
  }, [draft.jira_space_key, onResponsablePending, query, retrySearch, row.candidate_id,
    row.responsable, row.responsable_account_id, row.responsable_resolution_status, token]);
  async function searchAssignees() {
    lastSearched.current = "";
    setRetrySearch(value => value + 1);
  }
  async function chooseAssignee(accountId: string) {
    const selected = assignees.find(item => item.account_id === accountId);
    if (!selected?.account_id) return;
    const name = selected.display_name ?? query;
    const normalizedName = normalizeAssigneeQuery(name);
    lastSearched.current = normalizedName;
    pendingQuery.current = normalizedName;
    setValue(current => ({ ...current, responsable: name }));
    setResolutionStatus("VALIDATED_JIRA");
    await onSave(row.candidate_id, { responsable: name, responsable_account_id: selected.account_id,
      responsable_resolution_status: "VALIDATED_JIRA", responsable_lookup_query: query });
    emitOnboardingEvent("responsible:validated", { rowId: row.candidate_id });
    onResponsablePending(row.candidate_id, false);
    setAssignees([]);
  }
  const suggestions = row.suggestions.filter(item => !ignored.includes(item.field) && !row.ignored_suggestions.includes(item.field));
  const status = row.row_status ?? "NEEDS_REVIEW";
  const created = status === "CREATED";
  const alreadyPrepared = Boolean(row.proposal_id) && !created;
  const needsField = (field: string) => status === "NEEDS_REVIEW" && (row.row_errors ?? []).some(issue => issue.field === field);
  return <tr data-tour-id={status === "NEEDS_REVIEW" ? `needs-review-row-${row.candidate_id}` : status === "READY" ? `row-ready-${row.candidate_id}` : undefined} className={`minute-row minute-row-${status.toLowerCase()}`}>
    <td><div className="minute-activity-heading">
      <input data-tour-id={status === "READY" ? `activity-select-${row.candidate_id}` : undefined} type="checkbox" aria-label={`Seleccionar ${row.candidate_id} para preparar`} checked={selected}
        disabled={status !== "READY" || alreadyPrepared || Boolean(row.creation_status) || preparing}
        onChange={event => { onSelect(row.candidate_id, event.target.checked); if (event.target.checked) emitOnboardingEvent("row:selected", { rowId: row.candidate_id }); }} />
      <span className={`minute-row-status ${status.toLowerCase()}`}>{status === "READY" ? "✓ Lista" : status === "NEEDS_REVIEW" ? "⚠ Requiere revisión" : status === "INVALID" ? "✕ Error" : created ? "✓ Creada en Jira" : "⚠ Error de creación"}</span>
    </div>
      <textarea aria-label={`Actividad ${row.candidate_id}`} value={value.actividad ?? ""} disabled={created} onChange={e => change("actividad", e.target.value)} onBlur={() => save("actividad")} /><FieldState row={row} field="actividad" />
      {row.row_errors?.map(issue => <small key={`${issue.field}-${issue.code}`} className="draft-field-state review">{issue.message}</small>)}
      {created && row.jira_issue_key && <a href={row.jira_issue_url ?? `https://dpti.atlassian.net/browse/${row.jira_issue_key}`} target="_blank" rel="noreferrer">Abrir {row.jira_issue_key}</a>}
      {alreadyPrepared && <small className="draft-field-state neutral">Propuesta guardada en el historial.</small>}
      <details><summary>Ver evidencia</summary><strong>{row.source_section}</strong><blockquote>{row.source_evidence}</blockquote><small>{row.candidate_id} · {row.extraction_mode}</small></details></td>
    <td>{(() => { const mappedAreas = row.area_candidates ?? []; const availableAreas = mappedAreas.length
      ? mappedAreas.map(value => ({ key: value, value, label: value })) : areaOptions;
      return <><select data-tour-id={needsField("area_responsable") ? `area-field-${row.candidate_id}` : undefined} aria-label={`Área responsable ${row.candidate_id}`} value={value.area_responsable ?? ""} disabled={created || !availableAreas.length}
      onChange={e => {
        const selectedArea = availableAreas.find(option => option.value === e.target.value);
        void onSave(row.candidate_id, { area_responsable: selectedArea?.value ?? null, area_source: selectedArea ? "USER_SELECTED" : "UNRESOLVED" });
        if (selectedArea) emitOnboardingEvent("area:validated", { rowId: row.candidate_id });
      }}>
      <option value="">{mappedAreas.length ? "Selecciona un área" : "Selecciona un área"}</option>
      {value.area_responsable && !availableAreas.some(option => option.value === value.area_responsable) && <option value={value.area_responsable}>{value.area_responsable}</option>}
      {availableAreas.map(option => <option key={option.key} value={option.value}>{option.label}</option>)}</select>
      {row.area_status === "AMBIGUOUS" && <small className="draft-field-state review">Selecciona el área responsable: {row.area_candidates?.join(", ") || "por confirmar"}</small>}
      {row.area_mentions?.length ? <small className="draft-field-state neutral">Menciones sin asignación automática: {row.area_mentions.join(", ")}</small> : null}
      <small className="draft-field-state neutral">{mappedAreas.length ? "Áreas asociadas al responsable verificado; no se envía a Jira." : "Área local opcional; no se infiere desde Spaces Jira."}</small></> })()}</td>
    <td><input data-tour-id={needsField("responsable") ? `responsible-field-${row.candidate_id}` : undefined} aria-label={`Responsable ${row.candidate_id}`} disabled={created} value={value.responsable === "Por definir" ? "" : value.responsable ?? ""} placeholder="Por definir" onChange={e => {
      const input = e.target.value; const next = input || "Por definir"; const normalized = normalizeAssigneeQuery(input);
      lastSearched.current = ""; pendingQuery.current = normalized;
      setValue(current => ({ ...current, responsable: next, responsable_account_id: null }));
      setResolutionStatus(normalized.length >= 2 && normalized !== "por definir" ? "RESOLVING" : "UNRESOLVED");
      onResponsablePending(row.candidate_id, true);
      window.clearTimeout(responsibleSaveTimer.current);
      const status = normalized.length >= 2 && normalized !== "por definir" ? "RESOLVING" : "UNRESOLVED";
      responsibleSaveTimer.current = window.setTimeout(async () => {
        await onSaveRef.current(row.candidate_id, { responsable: next, responsable_account_id: null,
          responsable_resolution_status: status });
        if (status === "UNRESOLVED" && pendingQuery.current === normalized) onResponsablePending(row.candidate_id, false);
      }, 120);
    }} aria-autocomplete="list" aria-expanded={assignees.length > 0} />
      <button type="button" className="draft-cell-action" onClick={() => void searchAssignees()} disabled={lookup}>{lookup ? "Buscando…" : "Buscar en Jira"}</button>
      {assignees.length > 0 && <select aria-label={`Resultados responsable ${row.candidate_id}`} defaultValue="" onChange={e => void chooseAssignee(e.target.value)}><option value="">Selecciona una persona</option>{assignees.map(item => <option key={item.account_id ?? item.display_name} value={item.account_id ?? ""}>{item.display_name}</option>)}</select>}
      <ResponsableStatus status={resolutionStatus} row={row} /></td>
    <td>{draft.tracking_options.length ? <select data-tour-id={needsField("tipo_de_seguimiento") ? `tracking-field-${row.candidate_id}` : undefined} disabled={created} aria-label={`Tipo de seguimiento ${row.candidate_id}`} value={value.tipo_de_seguimiento ?? "Por definir"} onChange={e => {
      const selected = draft.tracking_options.find(option => option.label === e.target.value);
      change("tipo_de_seguimiento", e.target.value);
      void onSave(row.candidate_id, { tipo_de_seguimiento: e.target.value, tipo_de_seguimiento_id: selected?.jira_id ?? null });
      if (selected) emitOnboardingEvent("tracking:selected", { rowId: row.candidate_id });
    }}>
      <option>Por definir</option>{draft.tracking_options.map(option => <option key={option.jira_id ?? option.value} value={option.label}>{option.label}</option>)}</select> : <input aria-label={`Tipo de seguimiento ${row.candidate_id}`} value={value.tipo_de_seguimiento ?? "Por definir"}
        onChange={e => change("tipo_de_seguimiento", e.target.value)} onBlur={() => {
          if (value.tipo_de_seguimiento !== row.tipo_de_seguimiento) void onSave(row.candidate_id, { tipo_de_seguimiento: value.tipo_de_seguimiento, tipo_de_seguimiento_id: null });
        }} />}
      {!draft.tracking_options.length ? <small className="draft-field-state neutral">Catálogo Jira no disponible; puedes conservar un valor manual mientras se recupera.</small> : <FieldState row={row} field="tipo_de_seguimiento" />}</td>
    <td><input disabled={created} aria-label={`Fecha objetivo ${row.candidate_id}`} type="date" value={value.fecha_objetivo ?? ""} onChange={e => change("fecha_objetivo", e.target.value || null)} onBlur={() => save("fecha_objetivo")} /><FieldState row={row} field="fecha_objetivo" /></td>
    <td><textarea disabled={created} aria-label={`Proyecto o frente ${row.candidate_id}`} value={value.proyecto_o_frente ?? ""} onChange={e => change("proyecto_o_frente", e.target.value)} onBlur={() => save("proyecto_o_frente")} /><FieldState row={row} field="proyecto_o_frente" /></td>
    <td><textarea disabled={created} aria-label={`Contexto o resultado ${row.candidate_id}`} value={value.contexto_o_resultado ?? ""} onChange={e => change("contexto_o_resultado", e.target.value)} onBlur={() => save("contexto_o_resultado")} /><FieldState row={row} field="contexto_o_resultado" /></td>
    <td><textarea disabled={created} aria-label={`Comentarios ${row.candidate_id}`} value={value.comentarios ?? ""} onChange={e => change("comentarios", e.target.value)} onBlur={() => save("comentarios")} /><FieldState row={row} field="comentarios" />
      <button type="button" className="draft-delete" disabled={created} onClick={onDelete}>Eliminar fila</button>
      {status === "NEEDS_REVIEW" && <button type="button" className="button secondary compact" onClick={event => {
        const field = row.row_errors?.[0]?.field;
        const labels: Record<string, string> = {
          actividad: "Actividad", responsable: "Responsable", tipo_de_seguimiento: "Tipo de seguimiento",
          fecha_objetivo: "Fecha objetivo", proyecto_o_frente: "Proyecto o frente",
          contexto_o_resultado: "Contexto o resultado", comentarios: "Comentarios",
        };
        const label = labels[field ?? ""];
        const control = label ? event.currentTarget.closest("tr")?.querySelector<HTMLElement>(`[aria-label="${label} ${row.candidate_id}"]`) : null;
        control?.focus();
        control?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }}>Completar</button>}
      {status === "READY" && !alreadyPrepared && <button data-tour-id={`prepare-row-${row.candidate_id}`} type="button" className="button secondary compact" disabled={preparing}
        onClick={() => { emitOnboardingEvent("prepare:clicked", { rowId: row.candidate_id }); onPrepare([row.candidate_id]); }}>{preparing ? "Preparando…" : "Preparar esta tarea"}</button>}
      {row.row_warnings?.map((warning, index) => <small className="draft-field-state review" key={index}>{warning}</small>)}
      {!created && suggestions.map(suggestion => <div className="draft-suggestion" key={suggestion.field}><strong>Sugerencia IA disponible</strong><p>{suggestion.value}</p><button type="button" onClick={() => void onSave(row.candidate_id, { [suggestion.field]: suggestion.value } as Partial<MinuteDraftRow>)}>Aplicar</button><button type="button" onClick={() => { const next = [...row.ignored_suggestions, suggestion.field]; setIgnored(items => [...items, suggestion.field]); void onSave(row.candidate_id, { ignored_suggestions: next }); }}>Ignorar</button></div>)}</td>
  </tr>;
}

function ProjectResponsibleEditor({ token, draft, onSave }: {
  token: string; draft: MinuteExcelDraft;
  onSave: (changes: Partial<NonNullable<MinuteExcelDraft["document"]>>) => Promise<void>;
}) {
  const document = draft.document ?? {};
  const [value, setValue] = useState(document.project_responsible ?? "");
  const [matches, setMatches] = useState<JiraAssignee[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => { setValue(document.project_responsible ?? ""); }, [document.project_responsible]);
  async function search() {
    const query = value.trim();
    if (query.length < 2) return;
    setLoading(true); setMatches([]);
    try {
      const result = await findJiraAssigneesCached(token, draft.jira_space_key ?? "AT", query);
      setMatches(result.filter(item => item.active !== false && item.account_id));
    } finally { setLoading(false); }
  }
  async function choose(accountId: string) {
    const selected = matches.find(item => item.account_id === accountId);
    if (!selected?.account_id) return;
    await onSave({ project_responsible: selected.display_name ?? value,
      project_responsible_account_id: selected.account_id,
      project_responsible_resolution_status: "VALIDATED_JIRA",
      project_responsible_lookup_query: value });
    setMatches([]);
  }
  const status = document.project_responsible_resolution_status;
  return <section className="draft-project-responsible" aria-label="Responsable del proyecto">
    <strong>Responsable del proyecto</strong>
    <div><input aria-label="Responsable del proyecto" value={value} placeholder="Por definir"
      onChange={event => setValue(event.target.value)} onBlur={() => {
        const next = value.trim();
        if (next !== (document.project_responsible ?? "")) void onSave({ project_responsible: next || null,
          project_responsible_account_id: null,
          project_responsible_resolution_status: next ? "EXPLICIT_MINUTES" : "UNRESOLVED" });
      }} />
      <button type="button" className="button secondary compact" disabled={loading || value.trim().length < 2} onClick={() => void search()}>{loading ? "Buscando…" : "Verificar en Jira"}</button></div>
    {matches.length > 0 && <select aria-label="Resultados responsable del proyecto" defaultValue="" onChange={event => void choose(event.target.value)}><option value="">Selecciona una persona</option>{matches.map(item => <option key={item.account_id} value={item.account_id ?? ""}>{item.display_name}</option>)}</select>}
    {status === "VALIDATED_JIRA" || status === "AUTO_RESOLVED" ? <small className="draft-field-state valid">✓ Responsable del proyecto validado con Jira</small> :
      <small className="draft-field-state neutral">Contexto del proyecto; no se asigna automáticamente a ninguna tarea.</small>}
  </section>;
}

export function MinuteDraftPreview({ token, draft, setDraft, onSave, onSaveProjectResponsible, onCreated, onReanalyze }: {
  token: string; draft: MinuteExcelDraft; setDraft: (draft: MinuteExcelDraft) => void;
  onSave: (candidateId: string, changes: Partial<MinuteDraftRow>) => Promise<void>;
  onSaveProjectResponsible?: (changes: Partial<NonNullable<MinuteExcelDraft["document"]>>) => Promise<void>;
  onCreated: (proposal: Proposal) => void; onReanalyze: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pendingResponsableRows, setPendingResponsableRows] = useState<Set<string>>(new Set());
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());
  const [catalogLoading, setCatalogLoading] = useState(draft.catalog_status === "LOADING");
  const [areaOptions, setAreaOptions] = useState<Array<{ key: string; value: string; label: string }>>([]);
  const currentDraft = useRef(draft);
  const setDraftRef = useRef(setDraft);
  const onResponsablePending = useCallback((candidateId: string, pending: boolean) => {
    setPendingResponsableRows(current => {
      const next = new Set(current);
      if (pending) next.add(candidateId); else next.delete(candidateId);
      return next;
    });
  }, []);
  useEffect(() => { currentDraft.current = draft; }, [draft]);
  useEffect(() => {
    const review = draft.rows.find(row => row.row_status === "NEEDS_REVIEW");
    if (review) emitOnboardingEvent("row:needs-review", { rowId: review.candidate_id, missing: (review.row_errors ?? []).map(issue => issue.field) });
    const ready = draft.rows.find(row => row.row_status === "READY" && !row.proposal_id && !row.creation_status);
    if (ready) emitOnboardingEvent("row:ready", { rowId: ready.candidate_id });
  }, [draft]);
  useEffect(() => { setDraftRef.current = setDraft; }, [setDraft]);
  const loadTrackingCatalog = useCallback(async () => {
    setCatalogLoading(true);
    try {
      const result = await getMinuteTrackingCatalog(token, draft.draft_id);
      const current = currentDraft.current;
      const remoteRows = new Map(result.draft.rows.map(row => [row.candidate_id, row]));
      const rows = current.rows.map(local => {
        const remote = remoteRows.get(local.candidate_id);
        if (!remote || local.touched_fields.includes("tipo_de_seguimiento")) return local;
        const field = "tipo_de_seguimiento";
        return {
          ...local,
          tipo_de_seguimiento: remote.tipo_de_seguimiento,
          tipo_de_seguimiento_id: remote.tipo_de_seguimiento_id,
          field_status: { ...local.field_status, [field]: remote.field_status[field] },
          validation_errors: [
            ...local.validation_errors.filter(issue => issue.field !== field),
            ...remote.validation_errors.filter(issue => issue.field === field),
          ],
          row_status: remote.row_status,
          row_errors: [
            ...(local.row_errors ?? []).filter(issue => issue.field !== field),
            ...(remote.row_errors ?? []).filter(issue => issue.field === field),
          ],
          row_warnings: remote.row_warnings,
        };
      });
      const updated = { ...current, rows, tracking_options: result.options, catalog_status: result.state,
        tracking_field_id: result.field_id };
      setAreaOptions(result.area_options ?? []);
      currentDraft.current = updated;
      setDraftRef.current(updated);
    } catch {
      const current = currentDraft.current;
      const updated = { ...current, catalog_status: current.tracking_options.length ? "STALE" as const : "UNAVAILABLE" as const };
      currentDraft.current = updated;
      setDraftRef.current(updated);
    } finally { setCatalogLoading(false); }
  }, [draft.draft_id, token]);
  useEffect(() => { void loadTrackingCatalog(); }, [loadTrackingCatalog]);
  useEffect(() => {
    if (draft.enrichment.state !== "PENDING") return;
    let active = true;
    const timer = window.setInterval(() => {
      void getMinuteDraft(token, draft.draft_id).then(value => {
        if (active && value.enrichment.state !== "PENDING") setDraft(value);
      }).catch(() => undefined);
    }, 1200);
    return () => { active = false; window.clearInterval(timer); };
  }, [draft.draft_id, draft.enrichment.state, setDraft, token]);
  async function validate() {
    setBusy("validate"); setError("");
    try { const value = await validateMinuteDraft(token, draft.draft_id); setDraft(value); setMessage("Validación actualizada."); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible validar."); }
    finally { setBusy(""); }
  }
  async function add() {
    setBusy("add");
    try { setDraft(await addMinuteDraftRow(token, draft.draft_id, draft.version)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible agregar la fila."); }
    finally { setBusy(""); }
  }
  async function remove(row: MinuteDraftRow) {
    const hasContent = Boolean(row.actividad || (row.responsable && row.responsable !== "Por definir") || row.contexto_o_resultado || row.comentarios);
    if (hasContent && !window.confirm("¿Eliminar esta actividad del borrador local?")) return;
    setBusy(row.candidate_id);
    try { setDraft(await deleteMinuteDraftRow(token, draft.draft_id, row.candidate_id, draft.version)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible eliminar la fila."); }
    finally { setBusy(""); }
  }
  async function download() {
    setBusy("download"); setError("");
    try { await downloadMinuteDraftXlsx(token, draft.draft_id); setMessage("El Excel está listo para descargar."); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible descargar el Excel."); }
    finally { setBusy(""); }
  }
  async function proceed(candidateIds: string[]) {
    const eligible = draft.rows.filter(row => candidateIds.includes(row.candidate_id)
      && row.row_status === "READY" && !row.proposal_id && !row.creation_status);
    const ids = eligible.map(row => row.candidate_id);
    if (ids.length !== candidateIds.length || ids.some(id => pendingResponsableRows.has(id))) {
      setError("Sólo se pueden preparar actividades listas cuyos cambios ya estén guardados.");
      return;
    }
    if (!ids.length) return;
    setBusy("proposal"); setError("");
    try {
      const proposal = await createProposalFromMinuteDraft(token, draft.draft_id, ids);
      const updatedDraft = await getMinuteDraft(token, draft.draft_id);
      setDraft(updatedDraft);
      setSelectedRows(current => new Set([...current].filter(id => !ids.includes(id))));
      emitOnboardingEvent("proposal:ready", { rowId: ids[0] });
      onCreated(proposal);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Revisa los campos obligatorios antes de continuar."); }
    finally { setBusy(""); }
  }
  const summary = draft.validation_summary;
  const selectableRows = draft.rows.filter(row => row.row_status === "READY" && !row.proposal_id && !row.creation_status);
  const selectedReady = [...selectedRows].filter(id => selectableRows.some(row => row.candidate_id === id));
  return <section className="minute-draft-preview">
    <header data-tour-id="preview-summary"><span className="eyebrow">Vista previa · Plan de trabajo Jira v1.3</span><h2>Vista previa del plan</h2>
      <div className="draft-summary"><strong>{summary.activities} actividades detectadas</strong><span>{summary.complete} listas</span><span>{summary.needs_review} requieren revisión</span><span>{summary.created ?? 0} creadas</span><span>{summary.technical_errors} errores técnicos</span></div>
      <p>Origen: Minuta · versión {draft.version} · {draft.extraction_mode}</p>
      <ProjectResponsibleEditor token={token} draft={draft} onSave={onSaveProjectResponsible ?? (async () => undefined)} />
    </header>
    {draft.warnings.map((warning, index) => <div className="alert warning" key={index}>{warning}</div>)}
    {catalogLoading && <div className="alert" role="status">Cargando opciones Jira…</div>}
    {!catalogLoading && (draft.catalog_status === "UNAVAILABLE" || draft.catalog_status === "STALE") && <div className="alert warning" role="status">
      {draft.catalog_status === "STALE" ? "No se pudieron actualizar las opciones de Jira. Se conservan las opciones guardadas." : "No se pudieron actualizar las opciones de Jira."}
      <button type="button" className="button secondary" onClick={() => void loadTrackingCatalog()}>Reintentar catálogo</button>
    </div>}
    {draft.enrichment.state === "PENDING" && <div className="alert">Mejorando la redacción en segundo plano…</div>}
    {draft.enrichment.state === "FAILED" && <p className="minutes-origin-note">Las actividades fueron detectadas. Algunas mejoras automáticas no estuvieron disponibles.</p>}
    {message && <div role="status" className="alert success">{message}</div>}{error && <div role="alert" className="alert error">{error}</div>}
    <div className="draft-actions"><button className="button secondary" onClick={onReanalyze}>Volver a analizar</button><button className="button secondary" disabled={Boolean(busy)} onClick={() => void validate()}>Validar campos</button><button className="button secondary" disabled={Boolean(busy)} onClick={() => void download()}>{busy === "download" ? "Exportando…" : "Descargar Excel v1.3"}</button><button data-tour-id="prepare-selected" className="button primary" disabled={Boolean(busy) || !selectedReady.length || catalogLoading || selectedReady.some(id => pendingResponsableRows.has(id))} onClick={() => { emitOnboardingEvent("prepare:clicked", { rowId: selectedReady[0] }); void proceed(selectedReady); }}>{busy === "proposal" ? "Preparando…" : `Preparar seleccionadas (${selectedReady.length})`}</button></div>
    <p className="minutes-origin-note">Cada fila se valida por separado. Sólo las filas que marques y estén listas pasan a una propuesta; las pendientes se conservan aquí.</p>
    <div className="minute-grid-scroll"><table className="minute-grid"><thead><tr><th>Actividad *</th><th>Área responsable</th><th>Responsable *</th><th>Tipo de seguimiento *</th><th>Fecha objetivo</th><th>Proyecto o frente</th><th>Contexto o resultado</th><th>Comentarios</th></tr></thead><tbody>{draft.rows.map(row => <MinuteDraftTableRow key={row.candidate_id} row={row} draft={draft} token={token} onSave={onSave} onResponsablePending={onResponsablePending} onDelete={() => void remove(row)}
      selected={selectedReady.includes(row.candidate_id)} onSelect={(candidateId, checked) => setSelectedRows(current => { const next = new Set(current); checked ? next.add(candidateId) : next.delete(candidateId); return next; })}
      onPrepare={ids => void proceed(ids)} preparing={busy === "proposal" || pendingResponsableRows.has(row.candidate_id)} areaOptions={areaOptions} />)}</tbody></table></div>
    <button className="button secondary" disabled={Boolean(busy) || draft.rows.length >= 50} onClick={() => void add()}>Agregar actividad</button>
  </section>;
}

function MinutesItem({ item, token, proposalId, onUpdated, onEditing }: {
  item: ProposalItem; token: string; proposalId: string; onUpdated: (p: Proposal) => void; onEditing: (editing: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function toggle(value: boolean) { setEditing(value); onEditing(value); }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    const value = (name: string) => String(data.get(name) ?? "").trim();
    try {
      const updated = await editMinutesItem(token, proposalId, item.generated.row_id, {
        title: value("title"), description: value("context"), context: value("context"),
        responsible_candidate_text: value("responsible") || null, due_date_candidate: value("due") || null,
        area_responsable: value("area") || null,
        project_or_front: value("project") || null, comments: value("comments") || null,
      });
      onUpdated(updated); toggle(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible guardar."); }
    finally { setBusy(false); }
  }
  return <article className="minutes-card">
    <h3>{item.generated.title}</h3>
    {item.source.area_responsable && <p>Área responsable: {item.source.area_responsable} · {item.source.area_source === "LOCAL" ? "metadato local" : "catálogo Jira"}</p>}
    {item.source.area_status === "AMBIGUOUS" && <p className="minutes-warning">Área por confirmar: {(item.source.area_candidates ?? []).join(", ") || "hay menciones sin responsable claro"}. Las menciones no se enviarán a Jira como área.</p>}
    {item.source.area_mentions?.length ? <p>Áreas mencionadas en el texto, sin asignación automática: {item.source.area_mentions.join(", ")}</p> : null}
    <p>Responsable candidato: {item.source.responsable_display}</p>
    <p>⚠ Requiere revisión</p>
    {item.validation.warnings.map((warning, index) => <p className="minutes-warning" key={index}>{warning}</p>)}
    <details><summary>Ver origen</summary><p>{item.source.source_section || "Documento"}</p><blockquote>{item.source.source_evidence}</blockquote></details>
    {editing ? <form onSubmit={save} className="minutes-edit">
      <label>Actividad<input name="title" required maxLength={200} defaultValue={item.generated.title} /></label>
      <label>Responsable candidato<input name="responsible" maxLength={200} defaultValue={item.source.responsable_display === "Por definir" ? "" : item.source.responsable_display} /></label>
      <label>Área responsable<input name="area" maxLength={120} defaultValue={item.source.area_responsable ?? ""} /><small>Metadato local opcional; no se envía a Jira.</small></label>
      <label>Fecha objetivo<input name="due" type="date" defaultValue={item.source.fecha_objetivo ?? ""} /></label>
      <label>Proyecto o frente<input name="project" maxLength={300} defaultValue={item.source.frente_trabajo_origen ?? ""} /></label>
      <label>Contexto<textarea name="context" required maxLength={4000} defaultValue={item.generated.description} /></label>
      <label>Comentarios<textarea name="comments" maxLength={2000} defaultValue={item.source.comentarios ?? ""} /></label>
      {error && <p role="alert">{error}</p>}
      <div className="minutes-switch"><button className="button primary" disabled={busy}>Guardar cambios</button>
        <button className="button secondary" type="button" disabled={busy} onClick={() => toggle(false)}>Cancelar</button></div>
    </form> : <button className="button secondary" onClick={() => toggle(true)}>Editar</button>}
  </article>;
}

export function MinutesReview({ proposal, token, onUpdated, children }: {
  proposal: Proposal; token: string; onUpdated: (p: Proposal) => void; children: ReactNode;
}) {
  const [checked, setChecked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingCount, setEditingCount] = useState(0);
  const [error, setError] = useState("");
  const [enrichment, setEnrichment] = useState<MinutesEnrichment | null>(proposal.minutes?.enrichment ?? null);
  const [applyingSuggestion, setApplyingSuggestion] = useState("");
  useEffect(() => {
    if (!proposal.minutes?.enrichment) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const result = await getMinutesEnrichment(token, proposal.proposal_id);
        if (!active) return;
        setEnrichment(result);
        if (result.state === "PENDING") timer = window.setTimeout(() => void poll(), 1000);
      } catch { /* the deterministic Proposal remains usable if polling fails */ }
    };
    void poll();
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [proposal.minutes?.enrichment, proposal.proposal_id, token]);

  async function applySuggestion(item: ProposalItem, suggestion: NonNullable<MinutesEnrichment["suggestions"]>[number]) {
    setApplyingSuggestion(item.generated.row_id);
    setError("");
    try {
      const updated = await editMinutesItem(token, proposal.proposal_id, item.generated.row_id, {
        title: suggestion.title, description: suggestion.description, context: suggestion.description,
        responsible_candidate_text: item.source.responsable_display === "Por definir" ? null : item.source.responsable_display,
        due_date_candidate: item.source.fecha_objetivo, project_or_front: item.source.frente_trabajo_origen,
        comments: item.source.comentarios,
      });
      onUpdated(updated);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible aplicar la sugerencia."); }
    finally { setApplyingSuggestion(""); }
  }
  async function verify() {
    if (loading) return;
    setLoading(true); setError("");
    try { await preflightProposal(token, proposal.proposal_id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible verificar con Jira."); }
    finally { setChecked(true); setLoading(false); }
  }
  if (checked) return <>
    {error && <div role="alert" className="alert warning">{error}</div>}
    <button className="button secondary" onClick={() => setChecked(false)}>Volver a la minuta</button>
    {children}
  </>;
  const document = proposal.minutes!.document;
  const suggestions = new Map((enrichment?.suggestions ?? []).map((suggestion) => [suggestion.row_id, suggestion]));
  return <section className="minutes-results">
    <header><span className="eyebrow">02 · Propuesta generada</span><h2>{document.project || "Minuta analizada"}</h2>
      {document.date && <p>{document.date.split("-").reverse().join("/")}</p>}
      <p>{document.objective}</p>
      <h3>{proposal.items.length} actividades detectadas</h3>
      <p>{proposal.items.filter(item => item.generated.decision === "REVISAR").length} requieren tu revisión</p>
      <p className="minutes-origin-note">Detectadas directamente del documento. {enrichment?.state === "PENDING" ? "La mejora opcional con IA está en curso." : enrichment?.state === "FAILED" ? enrichment.message || "La mejora opcional con IA no estuvo disponible; la propuesta sigue usable." : enrichment?.state === "STALE" ? "La sugerencia quedó obsoleta porque hubo una edición humana." : enrichment?.state === "READY" && suggestions.size > 0 ? "Hay mejoras de redacción disponibles." : enrichment?.state === "READY" ? enrichment.message || "Las actividades ya tienen una redacción adecuada." : ""}</p>
      {document.participants.length > 0 && <p>Participantes: {document.participants.map(p => `${p.name}${p.role ? ` — ${p.role}` : ""}`).join(", ")}</p>}
    </header>
    {proposal.minutes!.warnings.map((warning, index) => <p role="status" className="alert warning" key={index}>{warning}</p>)}
    <button className="button primary" onClick={() => void verify()} disabled={loading || editingCount > 0}>{loading ? "Verificando con Jira..." : "Verificar con Jira"}</button>
    <p>Consulta responsables y catálogos para continuar con la revisión. Nada se creará en Jira.</p>
    {error && <div className="alert warning" role="alert">{error}</div>}
    {proposal.items.map(item => <div key={item.generated.row_id}>
      <MinutesItem item={item} token={token} proposalId={proposal.proposal_id}
        onUpdated={onUpdated} onEditing={value => setEditingCount(count => count + (value ? 1 : -1))} />
      {suggestions.has(item.generated.row_id) && enrichment?.state === "READY" && <section className="minutes-ai-suggestion" aria-label="Sugerencia de redacción IA">
        <strong>Sugerencia de redacción IA</strong><p>{suggestions.get(item.generated.row_id)!.title}</p>
        <button className="button secondary compact" disabled={Boolean(applyingSuggestion)} onClick={() => void applySuggestion(item, suggestions.get(item.generated.row_id)!)}> {applyingSuggestion === item.generated.row_id ? "Aplicando…" : "Aplicar sugerencia"}</button>
        <button className="button ghost compact" disabled={Boolean(applyingSuggestion)} onClick={() => setEnrichment(current => {
          if (!current) return current;
          const remaining = current.suggestions.filter(value => value.row_id !== item.generated.row_id);
          return { ...current, suggestions: remaining, message: remaining.length ? current.message : "Sugerencia ignorada." };
        })}>Ignorar</button>
      </section>}
    </div>)}
  </section>;
}
