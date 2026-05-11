import type { RecommendRequest, RecommendationResult } from '@/types/battery'

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
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
