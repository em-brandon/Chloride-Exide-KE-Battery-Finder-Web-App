import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  friendlyError,
  fetchMakes,
  fetchModels,
  fetchYears,
  fetchRecommendation,
  submitFeedback,
} from './api'
import type { RecommendRequest } from '@/types/battery'

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'content-type': 'application/json', ...init.headers },
  })
}

function htmlMaintenanceResponse() {
  return new Response('<html>maintenance</html>', {
    status: 503,
    headers: { 'content-type': 'text/html' },
  })
}

describe('friendlyError', () => {
  it('recognizes an aborted request as a timeout', () => {
    const err = new DOMException('aborted', 'AbortError')
    expect(friendlyError(err)).toBe('The request timed out. Please check your connection and try again.')
  })

  it('recognizes a fetch TypeError as no internet connection', () => {
    expect(friendlyError(new TypeError('Failed to fetch'))).toBe(
      'No internet connection. Please check your network and try again.'
    )
  })

  it.each([
    ['HTTP 429', 'Too many requests — please wait a moment and try again.'],
    ['HTTP 502', 'The server is temporarily unavailable. Please try again in a moment.'],
    ['HTTP 503', 'The server is temporarily unavailable. Please try again in a moment.'],
    ['HTTP 504', 'The server is temporarily unavailable. Please try again in a moment.'],
    ['HTTP 500', 'A server error occurred. Please try again.'],
    ['HTTP 422', 'Invalid request. Please check your inputs and try again.'],
    ['HTTP 401', 'Access denied. Please refresh the page and try again.'],
    ['HTTP 403', 'Access denied. Please refresh the page and try again.'],
    ['HTTP 404', 'No data found for the selected vehicle.'],
  ])('maps %s to a friendly message', (message, expected) => {
    expect(friendlyError(new Error(message))).toBe(expected)
  })

  it('passes through a non-HTTP-coded Error message verbatim', () => {
    expect(friendlyError(new Error('Something specific broke'))).toBe('Something specific broke')
  })

  it('falls back to a generic message for a non-Error value', () => {
    expect(friendlyError('a plain string')).toBe('Something went wrong. Please try again.')
  })
})

describe('fetchMakes / fetchModels / fetchYears / fetchRecommendation', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetchMakes returns the makes array on success', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ makes: ['Toyota', 'BMW'] }))
    await expect(fetchMakes()).resolves.toEqual(['Toyota', 'BMW'])
    expect(fetch).toHaveBeenCalledWith('/api/makes', expect.objectContaining({ signal: expect.anything() }))
  })

  it('fetchModels URL-encodes the make and returns models', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ models: ['Corolla'] }))
    await expect(fetchModels('Mercedes Benz')).resolves.toEqual(['Corolla'])
    expect(fetch).toHaveBeenCalledWith('/api/models/Mercedes%20Benz')
  })

  it('fetchYears URL-encodes make and model as query params', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ years: [2018, 2019] }))
    await expect(fetchYears('BMW', '3 Series')).resolves.toEqual([2018, 2019])
    expect(fetch).toHaveBeenCalledWith('/api/years?make=BMW&model=3%20Series')
  })

  it('fetchRecommendation POSTs the payload as JSON', async () => {
    const payload: RecommendRequest = { make: 'Toyota', model: 'Corolla', year: 2020, engine_cc: 1800, fuel_type: 'PETROL' }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ recommended_ah: 60 }))
    await fetchRecommendation(payload)
    expect(fetch).toHaveBeenCalledWith('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  })

  it('throws the backend detail message on a non-ok response', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'No match found' }, { status: 404 }))
    await expect(fetchMakes()).rejects.toThrow('No match found')
  })

  it('falls back to "HTTP <status>" when the error body has no detail', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('not json', { status: 500 }))
    await expect(fetchMakes()).rejects.toThrow('HTTP 500')
  })

  it('reloads the page on a maintenance-mode response instead of returning data', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(htmlMaintenanceResponse())
    const reload = vi.fn()
    Object.defineProperty(window, 'location', { value: { ...window.location, reload }, writable: true })
    await expect(fetchMakes()).rejects.toThrow('Service is in maintenance mode')
    expect(reload).toHaveBeenCalledOnce()
  })
})

describe('submitFeedback', () => {
  const payload = {
    vehicle_label: 'Toyota Corolla 2020',
    satisfaction: 5,
    accuracy: 'exact',
    wrong_parts: {},
    comments: '',
    submitted_at: new Date().toISOString(),
  }

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    localStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not send an Authorization header when no test-user token is stored', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await submitFeedback(payload)
    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect((init?.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('sends a Bearer token when a test-user token is stored', async () => {
    localStorage.setItem('test_user_token', 'abc123')
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await submitFeedback(payload)
    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer abc123')
  })

  it('throws on a non-ok response', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'Invalid rating' }, { status: 422 }))
    await expect(submitFeedback(payload)).rejects.toThrow('Invalid rating')
  })
})
