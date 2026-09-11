import { apiRequest } from "./client";

export interface OnboardingStepStatus {
  module: string;
  title: string;
  complete: boolean;
  headline: string;
}

export interface LoadSampleDataResponse {
  sop_documents_seeded: string[];
  module_results: Record<string, Record<string, unknown>>;
}

export function getOnboardingStatus() {
  return apiRequest<OnboardingStepStatus[]>("/onboarding/status");
}

export function isOnboardingComplete() {
  return apiRequest<{ complete: boolean }>("/onboarding/complete");
}

export function markOnboardingComplete() {
  return apiRequest<{ status: string }>("/onboarding/complete", { method: "POST" });
}

export function loadSampleData() {
  return apiRequest<LoadSampleDataResponse>("/onboarding/load-sample-data", { method: "POST" });
}
