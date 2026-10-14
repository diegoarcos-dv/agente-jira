import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { completeOnboarding, getOnboardingStatus, skipOnboarding } from "./api";
import { onboardingEventName, type OnboardingEventDetail, type OnboardingEventName } from "./onboardingEvents";

type TourPhase = "new-proposal" | "minutes-tab" | "minutes-input" | "analyze-minutes" | "analysis-wait" | "preview-summary" | "row-needs-review" | "responsible-field" | "area-field" | "tracking-field" | "row-ready" | "activity-select" | "prepare-selected" | "preparing" | "proposal-review";
type TourStatus = { version: number; current_version: number; required: boolean; completed_at?: string | null; skipped_at?: string | null };
type Placement = "top" | "bottom" | "left" | "right";
type TourStep = { title: string; description: string; target?: string; placement: Placement; progress: number };

const fieldPhases: Array<{ field: string; phase: TourPhase }> = [
  { field: "responsable", phase: "responsible-field" },
  { field: "area_responsable", phase: "area-field" },
  { field: "tipo_de_seguimiento", phase: "tracking-field" },
];
const phaseProgress: Record<TourPhase, number> = {
  "new-proposal": 1, "minutes-tab": 1, "minutes-input": 2, "analyze-minutes": 3, "analysis-wait": 3,
  "preview-summary": 4, "row-needs-review": 5, "responsible-field": 5, "area-field": 5,
  "tracking-field": 5, "row-ready": 6, "activity-select": 7, "prepare-selected": 8,
  preparing: 8, "proposal-review": 9,
};
const TOUR_PROGRESS_TOTAL = 9;

function findTarget(base: string | undefined, rowId?: string | null): HTMLElement | null {
  if (!base) return null;
  const elements = Array.from(document.querySelectorAll<HTMLElement>("[data-tour-id]"));
  const wanted = rowId ? `${base}-${rowId}` : base;
  return elements.find(element => element.dataset.tourId === wanted)
    ?? elements.find(element => element.dataset.tourId === base) ?? null;
}

function nextFieldPhase(missing: string[]): TourPhase | null {
  return fieldPhases.find(item => missing.includes(item.field))?.phase ?? null;
}

function getStep(phase: TourPhase, missing: string[]): TourStep {
  const progress = phaseProgress[phase];
  const steps: Record<TourPhase, TourStep> = {
    "new-proposal": { title: "Empieza aquí", description: "Abre Nueva propuesta para crear un nuevo plan de trabajo.", target: "new-proposal", placement: "right", progress },
    "minutes-tab": { title: "Elige una minuta", description: "Puedes pegar una minuta completa de reunión. Selecciona Pegar minuta para trabajar con sus acuerdos y pendientes.", target: "minutes-tab", placement: "bottom", progress },
    "minutes-input": { title: "1. Pega tu minuta aquí", description: "Usa acuerdos, pendientes o notas completas. El recorrido espera hasta que haya contenido suficiente.", target: "minutes-input", placement: "bottom", progress },
    "analyze-minutes": { title: "2. Analiza la minuta", description: "El agente organizará la información. Todavía no se creará nada en Jira.", target: "analyze-minutes", placement: "top", progress },
    "analysis-wait": { title: "Analizando tu minuta…", description: "Esperamos el resultado real del análisis antes de continuar.", placement: "bottom", progress },
    "preview-summary": { title: "3. Esta es tu vista previa", description: "Cada fila representa una actividad detectada. Puedes corregir cualquier dato antes de continuar.", target: "preview-summary", placement: "bottom", progress },
    "row-needs-review": { title: "Revisa esta actividad", description: missing.length ? `Esta actividad necesita: ${missing.join(", ")}. Completa sólo esos datos.` : "Estamos guardando la validación de esta actividad.", target: "needs-review-row", placement: "top", progress },
    "responsible-field": { title: "4. Selecciona al responsable", description: "Empieza a escribir un nombre y selecciona una cuenta real de Jira.", target: "responsible-field", placement: "bottom", progress },
    "area-field": { title: "Indica el área responsable", description: "Selecciona el área o equipo responsable usando el catálogo disponible.", target: "area-field", placement: "bottom", progress },
    "tracking-field": { title: "Selecciona el tipo de seguimiento", description: "Elige una opción del catálogo real de Jira.", target: "tracking-field", placement: "bottom", progress },
    "row-ready": { title: "¡Listo!", description: "Esta actividad ya está lista. Marca su casilla para prepararla; cada fila se valida por separado.", target: "row-ready", placement: "top", progress },
    "activity-select": { title: "Selecciona una actividad", description: "Marca la actividad lista que quieres preparar.", target: "activity-select", placement: "right", progress },
    "prepare-selected": { title: "5. Prepara las actividades listas", description: "Sólo las actividades listas pasan a una propuesta; las pendientes permanecen guardadas.", target: "prepare-selected", placement: "top", progress },
    preparing: { title: "Preparando la propuesta…", description: "Esperamos a que la propuesta quede lista antes de mostrar la revisión final.", target: "prepare-selected", placement: "top", progress },
    "proposal-review": { title: "Revisión final", description: "Antes de crear en Jira puedes revisar los datos, el responsable, la clasificación y la confirmación.", target: "proposal-review", placement: "bottom", progress },
  };
  return steps[phase];
}

function coachPosition(rect: DOMRect | null, placement: Placement): CSSProperties {
  if (!rect) return { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  const width = Math.min(352, window.innerWidth - 24); const height = 210; const gap = 16;
  let top = rect.bottom + gap; let left = rect.left;
  if (placement === "top" && rect.top >= height + gap) top = rect.top - height - gap;
  else if (placement === "left" && rect.left >= width + gap) { top = rect.top; left = rect.left - width - gap; }
  else if (placement === "right" && window.innerWidth - rect.right >= width + gap) { top = rect.top; left = rect.right + gap; }
  return { top: Math.max(12, Math.min(window.innerHeight - height - 12, top)), left: Math.max(12, Math.min(window.innerWidth - width - 12, left)) };
}

export function Onboarding({ token, displayName }: { token: string; displayName: string }) {
  const [status, setStatus] = useState<TourStatus | null>(null);
  const [active, setActive] = useState(false); const [welcome, setWelcome] = useState(false);
  const [phase, setPhase] = useState<TourPhase>("new-proposal"); const [activeRowId, setActiveRowId] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]); const [exitPrompt, setExitPrompt] = useState(false);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null); const [error, setError] = useState("");
  const coachRef = useRef<HTMLElement | null>(null);
  const phaseRef = useRef<TourPhase>("new-proposal");
  const activeRowRef = useRef<string | null>(null);
  const missingRef = useRef<string[]>([]);
  const step = useMemo(() => getStep(phase, missing), [missing, phase]);
  const moveTo = (next: TourPhase) => { phaseRef.current = next; setPhase(next); };
  const setRow = (next: string | null) => { activeRowRef.current = next; setActiveRowId(next); };
  const setMissingValue = (next: string[]) => { missingRef.current = next; setMissing(next); };

  useEffect(() => {
    let mounted = true;
    getOnboardingStatus(token).then(value => { if (mounted) { setStatus(value); if (value.required) setWelcome(true); } }).catch(() => undefined);
    return () => { mounted = false; };
  }, [token]);

  useEffect(() => {
    const repeat = () => { moveTo("new-proposal"); setRow(null); setMissingValue([]); setExitPrompt(false); setWelcome(true); setActive(false); };
    window.addEventListener(onboardingEventName("repeat"), repeat);
    return () => window.removeEventListener(onboardingEventName("repeat"), repeat);
  }, []);

  useEffect(() => {
    if (!active || welcome) return;
    const update = () => {
      const target = findTarget(step.target, activeRowId);
      if (target) { target.scrollIntoView?.({ behavior: "smooth", block: "center", inline: "nearest" }); setTargetRect(target.getBoundingClientRect()); }
      else setTargetRect(null);
    };
    update(); window.addEventListener("scroll", update, true); window.addEventListener("resize", update);
    const observer = new MutationObserver(update); observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    return () => { window.removeEventListener("scroll", update, true); window.removeEventListener("resize", update); observer.disconnect(); };
  }, [active, activeRowId, phase, step.target, welcome]);
  useEffect(() => { if (active && !welcome) coachRef.current?.focus(); }, [active, phase, welcome]);

  useEffect(() => {
    if (!active || welcome) return;
    const advance = (name: OnboardingEventName, detail: OnboardingEventDetail) => {
      const currentPhase = phaseRef.current;
      const currentRow = activeRowRef.current;
      const rowMatches = !detail.rowId || !currentRow || detail.rowId === currentRow;
      if (name === "view:new-proposal" && currentPhase === "new-proposal") return moveTo("minutes-tab");
      if (name === "minutes:selected" && currentPhase === "minutes-tab") return moveTo("minutes-input");
      if (name === "input:minutes" && currentPhase === "minutes-input") return moveTo("analyze-minutes");
      if (name === "analyze:clicked" && currentPhase === "analyze-minutes") return moveTo("analysis-wait");
      if (name === "analysis:completed" && currentPhase === "analysis-wait") return moveTo("preview-summary");
      if (name === "row:needs-review" && (currentPhase === "preview-summary" || currentPhase === "row-ready") && detail.rowId) { const pending = detail.missing ?? []; setRow(detail.rowId); setMissingValue(pending); moveTo(nextFieldPhase(pending) ?? "row-needs-review"); return; }
      if (name === "row:ready" && rowMatches && detail.rowId && ["preview-summary", "row-needs-review", "responsible-field", "area-field", "tracking-field"].includes(currentPhase)) { setRow(detail.rowId); setMissingValue([]); moveTo("row-ready"); return; }
      if (name === "row:selected" && rowMatches && detail.rowId && ["row-ready", "activity-select"].includes(currentPhase)) return moveTo("prepare-selected");
      if (name === "prepare:clicked" && detail.rowId && ["row-ready", "activity-select", "prepare-selected"].includes(currentPhase)) return moveTo("preparing");
      if (name === "proposal:ready" && currentPhase === "preparing") return moveTo("proposal-review");
      if (!rowMatches || !detail.rowId || !["responsible:validated", "area:validated", "tracking:selected"].includes(name)) return;
      const field = name === "responsible:validated" ? "responsable" : name === "area:validated" ? "area_responsable" : "tipo_de_seguimiento";
      const currentMissing = missingRef.current;
      if (!currentMissing.includes(field) || !["responsible-field", "area-field", "tracking-field"].includes(currentPhase)) return;
      const remaining = currentMissing.filter(item => item !== field); setMissingValue(remaining); moveTo(nextFieldPhase(remaining) ?? "row-needs-review");
    };
    const listeners: OnboardingEventName[] = ["view:new-proposal", "minutes:selected", "input:minutes", "analyze:clicked", "analysis:completed", "row:needs-review", "responsible:validated", "area:validated", "tracking:selected", "row:ready", "row:selected", "prepare:clicked", "proposal:ready"];
    const handlers = listeners.map(name => { const handler = (event: Event) => advance(name, (event as CustomEvent<OnboardingEventDetail>).detail ?? {}); window.addEventListener(onboardingEventName(name), handler); return [name, handler] as const; });
    return () => handlers.forEach(([name, handler]) => window.removeEventListener(onboardingEventName(name), handler));
  }, [active, welcome]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && (active || welcome)) { event.preventDefault(); setExitPrompt(true); } };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [active, welcome]);

  async function finish(kind: "complete" | "skip") {
    setError("");
    try { const next = kind === "complete" ? await completeOnboarding(token) : await skipOnboarding(token); setStatus(next); setActive(false); setWelcome(false); setExitPrompt(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible guardar el estado del recorrido."); }
  }
  if (!status || (!active && !welcome)) return null;
  const firstName = displayName.trim().split(/\s+/)[0] || "";
  return <div className="onboarding-layer" role="dialog" aria-modal="true" aria-live="polite" aria-label="Recorrido guiado">
    {!active && welcome ? <div className="onboarding-welcome-card"><span className="eyebrow">Recorrido guiado</span><h2>Hola, {firstName || "bienvenido"} 👋</h2><p>Te acompañaré para crear tu primera propuesta y aprender el flujo principal de Agente Jira.</p><p className="onboarding-safe-note">Durante este tutorial no se enviará nada a Jira automáticamente.</p>{error && <p className="alert error">{error}</p>}<div className="onboarding-actions"><button className="button secondary" onClick={() => void finish("skip")}>Omitir tutorial</button><button className="button primary" autoFocus onClick={() => { setWelcome(false); setActive(true); moveTo("new-proposal"); }}>Comenzar recorrido</button></div></div> : <><div className="onboarding-scrim" />{targetRect && <div className="onboarding-spotlight" style={{ top: targetRect.top - 6, left: targetRect.left - 6, width: targetRect.width + 12, height: targetRect.height + 12 }} />}<section ref={coachRef} tabIndex={-1} className={`onboarding-coach onboarding-${step.placement}`} aria-describedby="onboarding-step-description" style={coachPosition(targetRect, step.placement)}><span className="onboarding-step-count">Flujo principal · {step.progress} de {TOUR_PROGRESS_TOTAL}</span><h2>{step.title}</h2><p id="onboarding-step-description">{step.description}</p><div className="onboarding-actions"><button className="button ghost" onClick={() => void finish("skip")}>Omitir</button>{phase === "proposal-review" ? <button className="button primary" onClick={() => void finish("complete")}>Finalizar tutorial</button> : <span className="onboarding-waiting">Esperando tu acción…</span>}</div></section></>}
    {exitPrompt && <div className="onboarding-exit"><p>¿Quieres salir del recorrido?</p><button className="button secondary" onClick={() => setExitPrompt(false)}>Continuar</button><button className="button primary" onClick={() => void finish("skip")}>Salir</button></div>}
  </div>;
}
