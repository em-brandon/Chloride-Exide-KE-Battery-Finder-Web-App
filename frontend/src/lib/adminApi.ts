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
