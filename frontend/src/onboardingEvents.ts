export type OnboardingEventName =
  | "view:new-proposal"
  | "minutes:selected"
  | "input:minutes"
  | "analyze:clicked"
  | "analysis:completed"
  | "row:needs-review"
  | "responsible:validated"
  | "area:validated"
  | "tracking:selected"
  | "row:ready"
  | "row:selected"
  | "prepare:clicked"
  | "proposal:ready"
  | "repeat";

export interface OnboardingEventDetail {
  rowId?: string;
  missing?: string[];
  fields?: string[];
}

export function emitOnboardingEvent(name: OnboardingEventName, detail: OnboardingEventDetail = {}) {
  window.dispatchEvent(new CustomEvent(`agente:onboarding:${name}`, { detail }));
}

export function onboardingEventName(name: OnboardingEventName) {
  return `agente:onboarding:${name}`;
}
