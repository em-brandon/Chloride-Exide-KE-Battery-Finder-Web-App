/**
 * adminApi.ts — All fetch calls for the admin dashboard.
 *
 * All requests use `credentials: 'include'` so the HttpOnly session
 * cookie is sent automatically. A 401 response means the session has
 * expired or was revoked; the caller should redirect to /admin/login.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AdminStats {
  counts: {
    battery_specs: number
    vehicle_years: number
    vehicles_raw: number
    model_aliases: number
    inference_makes: number
    inference_models: number
    inference_records: number
  }
  db_reads: number
}

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'down'
  connected: boolean
  latency_ms: number | null
  pool_size: number
  pool_checked_out: number
  pool_usage_pct: number
}

export interface BatteryRow {
  id: number
  battery_code: string
  model_key: string
  ah: number
  cca_en: number | null
  technology: string
  origin: string | null
  brand: string | null
}

export interface BatteryListResponse {
  total: number
  page: number
  page_size: number
  items: BatteryRow[]
}

export interface BatteryPayload {
  battery_code: string
  model_key: string
  ah: number
  cca_en: number | null
  technology: string
}

export interface UploadResult {
  inserted: number
  updated: number
  skipped_unchanged: number
  rejected: number
  errors: { row: number; battery_code: string; reason: string }[]
}

export interface AuditEntry {
  id: number
  battery_id: number | null
  action: 'INSERT' | 'UPDATE' | 'DELETE'
  changed_by: string
  changed_at: string
  old_values: Record<string, unknown> | null
  new_values: Record<string, unknown> | null
}

export interface AuditLogResponse {
  total: number
  page: number
  items: AuditEntry[]
}

export interface SessionEntry {
  id: number
  created_at: string
  expires_at: string
  ip_address: string | null
  expired: boolean
}

// ---------------------------------------------------------------------------
// Base fetch with automatic 401 → redirect
// ---------------------------------------------------------------------------

class AdminAuthError extends Error {
  constructor() { super('Not authenticated') }
}

async function adminFetch<T>(
  input: string,
  init: RequestInit = {}
): Promise<T> {
  const res = await fetch(input, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  })

  if (res.status === 401) throw new AdminAuthError()

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T
  return res.json() as Promise<T>
}

// Re-export so callers can check `err instanceof AdminAuthError`
export { AdminAuthError }

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export async function adminLogin(username: string, password: string): Promise<void> {
  await adminFetch('/api/admin/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function adminLogout(): Promise<void> {
  await fetch('/api/admin/logout', { method: 'POST', credentials: 'include' })
}

export async function adminMe(): Promise<{ username: string }> {
  return adminFetch('/api/admin/me')
}

// ---------------------------------------------------------------------------
// Stats & Health
// ---------------------------------------------------------------------------

export async function fetchAdminStats(): Promise<AdminStats> {
  return adminFetch('/api/admin/stats')
}

export async function fetchHealthStatus(): Promise<HealthStatus> {
  return adminFetch('/api/admin/health')
}

// ---------------------------------------------------------------------------
// Batteries
// ---------------------------------------------------------------------------

export async function fetchBatteries(
  page = 1,
  pageSize = 50,
  search?: string,
  technology?: string,
): Promise<BatteryListResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (search)     params.set('search', search)
  if (technology) params.set('technology', technology)
  return adminFetch(`/api/admin/batteries?${params}`)
}

export async function addBattery(payload: BatteryPayload): Promise<{ id: number; battery_code: string }> {
  return adminFetch('/api/admin/batteries', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateBattery(id: number, payload: BatteryPayload): Promise<void> {
  await adminFetch(`/api/admin/batteries/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteBattery(id: number): Promise<void> {
  await adminFetch(`/api/admin/batteries/${id}`, { method: 'DELETE' })
}

export async function uploadBatteriesExcel(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/admin/batteries/upload', {
    method: 'POST',
    credentials: 'include',
    body: form,
    // Do NOT set Content-Type — browser sets it with the correct boundary
  })
  if (res.status === 401) throw new AdminAuthError()
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<UploadResult>
}

export function exportBatteriesUrl(): string {
  return '/api/admin/batteries/export'
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

export interface AuditFilters {
  action?: string        // comma-separated e.g. "INSERT,DELETE"
  changed_by?: string
  battery_code?: string
  date_from?: string     // YYYY-MM-DD
  date_to?: string       // YYYY-MM-DD
}

export async function fetchAuditLog(page = 1, pageSize = 50, filters: AuditFilters = {}): Promise<AuditLogResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (filters.action)       params.set('action', filters.action)
  if (filters.changed_by)   params.set('changed_by', filters.changed_by)
  if (filters.battery_code) params.set('battery_code', filters.battery_code)
  if (filters.date_from)    params.set('date_from', filters.date_from)
  if (filters.date_to)      params.set('date_to', filters.date_to)
  return adminFetch(`/api/admin/audit?${params}`)
}

export async function fetchAuditUsers(): Promise<{ users: string[] }> {
  return adminFetch('/api/admin/audit/users')
}

// ---------------------------------------------------------------------------
// Cache
// ---------------------------------------------------------------------------

export async function refreshCache(): Promise<void> {
  await adminFetch('/api/admin/cache/refresh', { method: 'POST' })
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export async function fetchSessions(): Promise<{ sessions: SessionEntry[] }> {
  return adminFetch('/api/admin/sessions')
}

export async function revokeSession(id: number): Promise<void> {
  await adminFetch(`/api/admin/sessions/${id}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export interface FeedbackEntry {
  id: number
  vehicle_label: string
  satisfaction: number
  accuracy: 'exact' | 'close' | 'wrong' | 'unsure' | null
  wrong_parts: Record<string, boolean> | null
  comments: string | null
  submitted_at: string
  ip_address: string | null
  test_username: string | null
  input_type: string | null
  match_confidence: number | null
  match_type: string | null
  recommended_battery: string | null
}

export interface FeedbackListResponse {
  total: number
  page: number
  page_size: number
  items: FeedbackEntry[]
}

export interface FeedbackSummary {
  total: number
  avg_satisfaction: number | null
  accuracy_breakdown: Record<string, number>
  star_breakdown: Record<string, number>
}

export async function fetchFeedback(
  page = 1,
  page_size = 25,
  accuracy?: string,
): Promise<FeedbackListResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(page_size) })
  if (accuracy) params.set('accuracy', accuracy)
  return adminFetch(`/api/admin/feedback?${params}`)
}

export async function fetchFeedbackSummary(): Promise<FeedbackSummary> {
  return adminFetch('/api/admin/feedback/summary')
}

export async function downloadFeedbackPdf(accuracy?: string): Promise<void> {
  const params = new URLSearchParams()
  if (accuracy) params.set('accuracy', accuracy)
  const url = `/api/admin/feedback/export-pdf${params.toString() ? `?${params}` : ''}`
  const res = await fetch(url, { credentials: 'include' })
  if (res.status === 401) throw new AdminAuthError()
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const match = disposition.match(/filename="([^"]+)"/)
  link.download = match ? match[1] : 'feedback_report.pdf'
  link.click()
  URL.revokeObjectURL(link.href)
}

export async function downloadFeedbackCsv(accuracy?: string): Promise<void> {
  const params = new URLSearchParams()
  if (accuracy) params.set('accuracy', accuracy)
  const url = `/api/admin/feedback/export-csv${params.toString() ? `?${params}` : ''}`
  const res = await fetch(url, { credentials: 'include' })
  if (res.status === 401) throw new AdminAuthError()
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const match = disposition.match(/filename="([^"]+)"/)
  link.download = match ? match[1] : 'feedback_report.csv'
  link.click()
  URL.revokeObjectURL(link.href)
}

// ---------------------------------------------------------------------------
// Test-user sessions (admin view)
// ---------------------------------------------------------------------------

export interface TestSessionEntry {
  id:           number
  username:     string
  user_id:      number
  created_at:   string
  expires_at:   string
  last_seen_at: string | null
  ip_address:   string | null
  user_agent:   string | null
  expired:      boolean
}

export interface TestUserEntry {
  id:              number
  username:        string
  email:           string | null
  created_at:      string
  is_active:       boolean
  active_sessions: number
}

export async function fetchTestSessions(): Promise<{ sessions: TestSessionEntry[] }> {
  return adminFetch('/api/admin/test-sessions')
}

export async function revokeTestSession(id: number): Promise<void> {
  await adminFetch(`/api/admin/test-sessions/${id}`, { method: 'DELETE' })
}

export async function fetchTestUsers(): Promise<{ users: TestUserEntry[] }> {
  return adminFetch('/api/admin/test-users')
}

// ---------------------------------------------------------------------------
// Web-validate pipeline
// ---------------------------------------------------------------------------

export interface WebValidateStatus {
  run_id:           string | null
  status:           'idle' | 'running' | 'paused' | 'done' | 'cancelled' | 'error'
  total:            number
  processed:        number
  found:            number
  not_found:        number
  current_provider: string | null
  current_combo:    string | null
  provider_counts:  { duckduckgo: number; google_cse: number; tavily: number }
  logs:              string[]
  started_at:        string | null
  phase1_total:      number
  phase1_processed:  number
  phase2_started_at: string | null
  finished_at:       string | null
  error_detail:      string | null
}

export interface QuotaInfo {
  provider:    string
  calls_made:  number
  quota_limit: number   // -1 = unlimited
  pct_used:    number
}

export interface CoverageInfo {
  total:              number
  matched:            number
  unmatched:          number
  pct_matched:        number
  master_count:       number
  staging_count:      number
  unmatched_vehicles: Array<{
    make_n:     string
    model_n:    string
    year:       number
    engine_cc:  number | null
    fuel_type:  string | null
  }>
  total_buckets:     number
  resolved_buckets:  number
  remaining_buckets: number
  web_cache_size:    number
}

export interface ProviderInfo {
  provider:         string
  configured:       boolean
  always_available: boolean
}

export async function runWebValidatePipeline(
  enabledProviders?: string[],
  phase: 'phase1' | 'phase2' | 'both' = 'phase1',
): Promise<{ run_id: string }> {
  return adminFetch('/api/admin/pipeline/web-validate/run', {
    method: 'POST',
    body: JSON.stringify({ enabled_providers: enabledProviders ?? null, phase }),
  })
}

export async function getWebValidateProviders(): Promise<ProviderInfo[]> {
  return adminFetch('/api/admin/pipeline/web-validate/providers')
}

export async function getWebValidateStatus(): Promise<WebValidateStatus> {
  return adminFetch('/api/admin/pipeline/web-validate/status')
}

export async function pauseWebValidate(): Promise<void> {
  await adminFetch('/api/admin/pipeline/web-validate/pause', { method: 'POST' })
}

export async function resumeWebValidate(): Promise<void> {
  await adminFetch('/api/admin/pipeline/web-validate/resume', { method: 'POST' })
}

export interface CancelWebValidateResult {
  detail:         string
  staged_count:   number
  invalid_count:  number
  conflict_count: number
}

export async function cancelWebValidate(): Promise<CancelWebValidateResult> {
  return adminFetch('/api/admin/pipeline/web-validate/cancel', { method: 'POST' })
}

export async function getPipelineQuotas(): Promise<QuotaInfo[]> {
  return adminFetch('/api/admin/pipeline/quotas')
}

export async function getWebValidateCoverage(): Promise<CoverageInfo> {
  return adminFetch('/api/admin/pipeline/web-validate/coverage')
}

export async function resetWebValidateCache(): Promise<{ deleted: boolean; rows_cleared: number }> {
  return adminFetch('/api/admin/pipeline/web-validate/reset-cache', { method: 'POST' })
}

export interface MatchedVehicleRow {
  make_n:       string
  model_n:      string
  year:         number
  battery_code: string | null
  ah:           number | null
  technology:   string | null
  source:       string | null
  validated_at: string | null
}

export interface MatchedVehiclesResponse {
  total:     number
  page:      number
  page_size: number
  items:     MatchedVehicleRow[]
}

export async function getWebValidateMatched(
  page = 1,
  pageSize = 50,
  search = '',
): Promise<MatchedVehiclesResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (search) params.set('search', search)
  return adminFetch(`/api/admin/pipeline/web-validate/matched?${params}`)
}

// ---------------------------------------------------------------------------
// Staging area
// ---------------------------------------------------------------------------

export interface ConflictDetail {
  current: { ah: number | null; technology: string | null; source: string; run_id: string | null }
  staged:  { ah: number | null; technology: string | null; source: string }
}

export interface StagingRow {
  id:              number
  make_n:          string
  model_n:         string
  year:            number
  battery_code:    string | null
  ah:              number | null
  technology:      string | null
  source:          string | null
  engine_cc:       number | null
  fuel_type:       string | null
  staged_at:       string
  is_valid:        boolean
  invalid_reason:  string | null
  conflict:        boolean
  conflict_detail: ConflictDetail | null
}

export interface StagingAreaResponse {
  has_staging:    boolean
  total:          number
  valid_count:    number
  invalid_count:  number
  conflict_count: number
  run_id:         string | null
  page:           number
  page_size:      number
  items:          StagingRow[]
}

export interface ConflictResolution {
  make_n:  string
  model_n: string
  year:    number
  keep:    'staging' | 'current'
}

export interface CommitStagingResult {
  version_id:         string
  version_number:     number
  committed:          number
  removed_invalid:    number
  conflicts_resolved: number
}

export async function getStagingArea(
  page = 1,
  pageSize = 50,
  filter: 'all' | 'valid' | 'invalid' | 'conflicts' = 'all',
): Promise<StagingAreaResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    filter,
  })
  return adminFetch(`/api/admin/pipeline/web-validate/staging?${params}`)
}

export async function getStagingPreCommit(): Promise<{
  conflict_count: number
  conflicts: Array<{ make_n: string; model_n: string; year: number; conflict_detail: ConflictDetail }>
}> {
  return adminFetch('/api/admin/pipeline/web-validate/staging/pre-commit')
}

export async function commitStagingArea(
  conflictResolutions: ConflictResolution[] = [],
): Promise<CommitStagingResult> {
  return adminFetch('/api/admin/pipeline/web-validate/staging/commit', {
    method: 'POST',
    body: JSON.stringify({ conflict_resolutions: conflictResolutions }),
  })
}

export async function discardStagingArea(): Promise<{ discarded: number }> {
  return adminFetch('/api/admin/pipeline/web-validate/staging/discard', { method: 'POST' })
}

export async function patchStagingRow(
  rowId: number,
  patch: { ah: number | null; technology: string | null },
): Promise<StagingRow> {
  return adminFetch(`/api/admin/pipeline/web-validate/staging/${rowId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

// ---------------------------------------------------------------------------
// Versioning
// ---------------------------------------------------------------------------

export interface ValidationVersion {
  id:              string
  version_number:  number
  committed_at:    string
  run_id:          string | null
  committed_count: number
  removed_count:   number
  conflict_count:  number
  notes:           string | null
  committed_by:    string | null
  initiated_by:    string | null
}

export interface ValidationVersionsResponse {
  total:     number
  page:      number
  page_size: number
  items:     ValidationVersion[]
}

export interface ChangelogEntry {
  make_n:      string
  model_n:     string
  year:        number
  change_type: 'added' | 'updated' | 'removed'
  old_values:  Record<string, unknown> | null
  new_values:  Record<string, unknown> | null
}

export interface VersionChangelogResponse {
  version:   ValidationVersion
  total:     number
  page:      number
  page_size: number
  items:     ChangelogEntry[]
}

export async function getValidationVersions(page = 1, pageSize = 20): Promise<ValidationVersionsResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return adminFetch(`/api/admin/pipeline/web-validate/versions?${params}`)
}

export async function getVersionChangelog(
  versionId: string,
  page = 1,
  pageSize = 100,
): Promise<VersionChangelogResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return adminFetch(`/api/admin/pipeline/web-validate/versions/${versionId}/changelog?${params}`)
}

export interface RevertVersionResult {
  version_id:              string
  version_number:          number
  reverted_version_number: number
  committed_by:            string
  changes:                 number
}

export async function revertVersion(versionId: string): Promise<RevertVersionResult> {
  return adminFetch(`/api/admin/pipeline/web-validate/versions/${versionId}/revert`, { method: 'POST' })
}

// ---------------------------------------------------------------------------
// Staleness
// ---------------------------------------------------------------------------

export interface StalenessInfo {
  last_run_completed_at:      string | null
  vehicles_last_updated_at:   string | null
  new_vehicles_since_last_run: number
  stale:                      boolean
}

export async function getPipelineStaleness(): Promise<StalenessInfo> {
  return adminFetch('/api/admin/pipeline/web-validate/staleness')
}

// ---------------------------------------------------------------------------
// Maintenance mode
// ---------------------------------------------------------------------------

export interface MaintenanceModeStatus {
  enabled: boolean
}

export async function getMaintenanceMode(): Promise<MaintenanceModeStatus> {
  return adminFetch('/api/admin/maintenance')
}

export async function setMaintenanceMode(enabled: boolean): Promise<MaintenanceModeStatus> {
  return adminFetch('/api/admin/maintenance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
}
