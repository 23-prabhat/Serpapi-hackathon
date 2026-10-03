import type { components } from "./generated/schema";

export type Programme = components["schemas"]["ProgrammeRead"];
export type CheckAccepted = components["schemas"]["CheckAccepted"];
export type Check = components["schemas"]["CheckRead"];
export type ApplicantProfile = components["schemas"]["ApplicantProfile"];
export type Run = components["schemas"]["RunRead"];
export type RunComparison = components["schemas"]["RunComparisonRead"];
export type Report = components["schemas"]["ReportRead"];
export type Deadline = components["schemas"]["DeadlineRead"];
export type EvidenceReference = components["schemas"]["EvidenceReference"];
export type Evidence = components["schemas"]["EvidenceRead"];
export type Example = components["schemas"]["ExampleRead"];
export type ApiError = {
  error?: { code?: string; message?: string; retryable?: boolean };
};
