import { describe, it, expect, vi, beforeEach } from 'vitest'
import { isMaintenanceResponse, redirectToMaintenance } from './maintenance'

function response(status: number, contentType: string | null): Response {
  const headers = new Headers()
  if (contentType) headers.set('content-type', contentType)
  return { status, headers } as Response
}

describe('isMaintenanceResponse', () => {
  it('is true for a 503 with an HTML content-type', () => {
    expect(isMaintenanceResponse(response(503, 'text/html; charset=utf-8'))).toBe(true)
  })

  it('is false for a 503 with a JSON content-type (a real API 503, not maintenance)', () => {
    expect(isMaintenanceResponse(response(503, 'application/json'))).toBe(false)
  })

  it('is false for a non-503 status even with HTML content-type', () => {
    expect(isMaintenanceResponse(response(200, 'text/html'))).toBe(false)
  })

  it('is false when there is no content-type header at all', () => {
    expect(isMaintenanceResponse(response(503, null))).toBe(false)
  })
})

describe('redirectToMaintenance', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('reloads the page and throws so callers stop using stale state', () => {
    const reload = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, reload },
      writable: true,
    })
    expect(() => redirectToMaintenance()).toThrow('Service is in maintenance mode')
    expect(reload).toHaveBeenCalledOnce()
  })
})
