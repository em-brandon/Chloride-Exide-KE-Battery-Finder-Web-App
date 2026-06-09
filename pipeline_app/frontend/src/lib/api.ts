const BASE = '/api'

function getToken(): string | null {
  return localStorage.getItem('pipeline_token')
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = getToken()
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail?.detail || res.statusText)
  }
  return res.json() as Promise<T>
}

export const api = {
  // Auth
  login:  (username: string, password: string) =>
    req<{ token: string; username: string }>('POST', '/auth/login', { username, password }),
  logout: () => req<void>('POST', '/auth/logout'),
  me:     () => req<{ username: string }>('GET', '/auth/me'),

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
    req<{ total: number; items: Record<string, unknown>[] }>('GET', `/pipeline/web-validate/matched?page=${page}&page_size=${pageSize}&search=${encodeURIComponent(search)}`),
  wvResetCache: () => req<{ deleted: boolean; rows_cleared: number }>('POST', '/pipeline/web-validate/reset-cache'),
  wvStaleness:  () => req<{ stale: boolean; new_vehicles_since_last_run: number }>('GET', '/pipeline/web-validate/staleness'),

  // Quotas
  quotas: () => req<{ provider: string; calls_made: number; quota_limit: number; pct_used: number }[]>('GET', '/pipeline/quotas'),

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
    const token = getToken()
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/pipeline/crsp/upload`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
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
