const BASE = import.meta.env.PROD ? '/pipeline/api' : '/api'

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail?.detail || res.statusText)
  }
  return res.json() as Promise<T>
}

export type LogEntry = {
  level: 'info' | 'success' | 'warn' | 'error' | 'milestone'
  message: string
  ts: string
}

export type SessionInfo = {
  id: number
  created_at: string
  expires_at: string
  ip_address: string | null
  is_current: boolean
}

export type MasterRecord = {
  id: number
  make_n: string
  model_n: string
  year: number
  battery_code: string | null
  ah: number | null
  technology: string | null
  source: string | null
  validated_at: string | null
}

export const api = {
  // Auth
  login:         (username: string, password: string) =>
    req<{ username: string }>('POST', '/auth/login', { username, password }),
  logout:        () => req<void>('POST', '/auth/logout'),
  me:            () => req<{ username: string }>('GET', '/auth/me'),
  sessions:      () => req<SessionInfo[]>('GET', '/auth/sessions'),
  revokeSession: (id: number) => req<void>('DELETE', `/auth/sessions/${id}`),

  // Web Validate
  wvRun:        (enabled_providers: string[] | null, phase: string) =>
    req<{ run_id: string }>('POST', '/pipeline/web-validate/run', { enabled_providers, phase }),
  wvStatus:     () => req<Record<string, unknown>>('GET', '/pipeline/web-validate/status'),
  wvPause:      () => req<void>('POST', '/pipeline/web-validate/pause'),
  wvResume:     () => req<void>('POST', '/pipeline/web-validate/resume'),
  wvCancel:     () => req<void>('POST', '/pipeline/web-validate/cancel'),
  wvProviders:  () => req<{ provider: string; configured: boolean; always_available: boolean }[]>('GET', '/pipeline/web-validate/providers'),
  wvCoverage:   () => req<Record<string, unknown>>('GET', '/pipeline/web-validate/coverage'),
  wvMatched:    (page: number, pageSize: number, search: string) =>
    req<{ total: number; items: MasterRecord[] }>('GET', `/pipeline/web-validate/matched?page=${page}&page_size=${pageSize}&search=${encodeURIComponent(search)}`),
  patchMaster:  (id: number, body: { ah?: number | null; technology?: string | null; battery_code?: string | null; scope?: 'single' | 'bucket' }) =>
    req<{ ok: boolean; version_number: number; rows_updated: number }>('PATCH', `/pipeline/web-validate/master/${id}`, body),
  deleteMaster: (id: number) =>
    req<{ ok: boolean }>('DELETE', `/pipeline/web-validate/master/${id}`),
  wvResetCache: () => req<{ deleted: boolean; rows_cleared: number }>('POST', '/pipeline/web-validate/reset-cache'),
  wvStaleness:  () => req<{ stale: boolean; new_vehicles_since_last_run: number }>('GET', '/pipeline/web-validate/staleness'),

  // Quotas
  quotas: () => req<{ provider: string; calls_made: number; quota_limit: number; pct_used: number; period_end: string | null; days_until_reset: number | null }[]>('GET', '/pipeline/quotas'),

  // Staging
  staging:      (page: number, filter: string) =>
    req<Record<string, unknown>>('GET', `/pipeline/web-validate/staging?page=${page}&filter=${filter}`),
  patchStaging: (id: number, ah: number | null, technology: string | null) =>
    req<Record<string, unknown>>('PATCH', `/pipeline/web-validate/staging/${id}`, { ah, technology }),
  preCommit:    () => req<{ conflict_count: number; conflicts: unknown[] }>('GET', '/pipeline/web-validate/staging/pre-commit'),
  commit:       (conflict_resolutions: unknown[]) =>
    req<Record<string, unknown>>('POST', '/pipeline/web-validate/staging/commit', { conflict_resolutions }),
  discard:      () => req<{ discarded: number }>('POST', '/pipeline/web-validate/staging/discard'),
  fixAh:        () => req<{ fixed: number; unchanged: number; failed: number }>('POST', '/pipeline/web-validate/staging/fix-ah'),

  // Versions
  versions:   (page: number) =>
    req<{ total: number; items: Record<string, unknown>[] }>('GET', `/pipeline/web-validate/versions?page=${page}`),
  changelog:  (versionId: string) =>
    req<{ version: Record<string, unknown>; items: Record<string, unknown>[] }>('GET', `/pipeline/web-validate/versions/${versionId}/changelog`),
  revert:     (versionId: string) =>
    req<Record<string, unknown>>('POST', `/pipeline/web-validate/versions/${versionId}/revert`),

  // CRSP
  crspUpload: async (file: File): Promise<{ file_path: string }> => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/pipeline/crsp/upload`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(detail?.detail || res.statusText)
    }
    return res.json()
  },
  crspRun:    (input_file: string) => req<{ detail: string }>('POST', '/pipeline/crsp/run', { input_file }),
  crspStatus: () => req<Record<string, unknown>>('GET', '/pipeline/crsp/status'),
  crspCancel: () => req<{ detail: string }>('POST', '/pipeline/crsp/cancel'),
}
