import type { RecommendRequest, RecommendationResult } from '@/types/battery'

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function friendlyError(err: unknown): string {
  if (err instanceof DOMException && err.name === 'AbortError')
    return 'The request timed out. Please check your connection and try again.'

  if (err instanceof TypeError && (
    err.message.includes('fetch') ||
    err.message.includes('NetworkError') ||
    err.message.includes('network')
  )) return 'No internet connection. Please check your network and try again.'

  if (err instanceof Error) {
    const msg = err.message
    if (msg.includes('HTTP 429')) return 'Too many requests — please wait a moment and try again.'
    if (msg.includes('HTTP 502') || msg.includes('HTTP 503') || msg.includes('HTTP 504'))
      return 'The server is temporarily unavailable. Please try again in a moment.'
    if (msg.includes('HTTP 500')) return 'A server error occurred. Please try again.'
    if (msg.includes('HTTP 422')) return 'Invalid request. Please check your inputs and try again.'
    if (msg.includes('HTTP 401') || msg.includes('HTTP 403'))
      return 'Access denied. Please refresh the page and try again.'
    if (msg.includes('HTTP 404')) return 'No data found for the selected vehicle.'
    if (msg) return msg
  }

  return 'Something went wrong. Please try again.'
}

export async function fetchMakes(): Promise<string[]> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 8000)
  try {
    const res = await fetch('/api/makes', { signal: controller.signal })
    const data = await handleResponse<{ makes: string[] }>(res)
    return data.makes
  } finally {
    clearTimeout(timer)
  }
}

export async function fetchModels(make: string): Promise<string[]> {
  const res = await fetch(`/api/models/${encodeURIComponent(make)}`)
  const data = await handleResponse<{ models: string[] }>(res)
  return data.models
}

export async function fetchYears(make: string, model: string): Promise<number[]> {
  const res = await fetch(
    `/api/years?make=${encodeURIComponent(make)}&model=${encodeURIComponent(model)}`
  )
  const data = await handleResponse<{ years: number[] }>(res)
  return data.years
}

export async function fetchRecommendation(
  payload: RecommendRequest
): Promise<RecommendationResult> {
  const res = await fetch('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handleResponse<RecommendationResult>(res)
}

export interface BatterySpecResult {
  battery_code: string
  model_key: string
  ah: number | null
  cca: number | null
  technology: string | null
  brand: string | null
  origin: string | null
  match_type: 'direct' | 'close'
}

export async function searchBatteryBySpecs(
  ah?: number,
  cca?: number,
): Promise<{ results: BatterySpecResult[]; count: number }> {
  const params = new URLSearchParams()
  if (ah  != null) params.set('ah',  String(ah))
  if (cca != null) params.set('cca', String(cca))
  const res = await fetch(`/api/batteries/search?${params}`)
  return handleResponse<{ results: BatterySpecResult[]; count: number }>(res)
}

export interface FeedbackPayload {
  vehicle_label: string
  satisfaction: number
  accuracy: string
  wrong_parts: { [key: string]: boolean }
  comments: string
  submitted_at: string
  input_type?: string
  match_confidence?: number
  match_type?: string
  recommended_battery?: string
}

export async function submitFeedback(payload: FeedbackPayload): Promise<void> {
  const token = localStorage.getItem('test_user_token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch('/api/feedback', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
}
