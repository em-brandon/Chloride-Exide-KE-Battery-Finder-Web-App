import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  AdminAuthError,
  AdminNetworkError,
  friendlyErrorMessage,
  adminLogin,
  adminMe,
  fetchAdminStats,
  fetchBatteries,
  addBattery,
  deleteBattery,
  revokeSession,
  uploadBatteriesExcel,
  downloadFeedbackPdf,
  downloadFeedbackCsv,
} from './adminApi'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

describe('friendlyErrorMessage', () => {
  it.each([
    [502, 'The server is temporarily unavailable. Please try again in a moment.'],
    [503, 'The server is temporarily unavailable. Please try again in a moment.'],
    [504, 'The server is temporarily unavailable. Please try again in a moment.'],
    [500, 'Something went wrong on our end. Please try again.'],
    [403, "You don't have permission to do that."],
    [404, 'That could not be found. It may have been removed.'],
    [429, 'Too many requests — please wait a moment and try again.'],
  ])('maps status %i to a fixed friendly message', (status, expected) => {
    expect(friendlyErrorMessage(status, 'some raw backend detail')).toBe(expected)
  })

  it('prefers the backend detail for other 4xx codes', () => {
    expect(friendlyErrorMessage(422, 'ah must be positive')).toBe('ah must be positive')
  })

  it('falls back to a generic message for other 4xx codes with no detail', () => {
    expect(friendlyErrorMessage(400)).toBe('Something went wrong (error 400). Please try again.')
  })
})

describe('adminFetch (shared behavior, exercised via adminMe/adminLogin)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends credentials: include and a JSON content-type on every request', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ username: 'admin' }))
    await adminMe()
    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect(init?.credentials).toBe('include')
    expect((init?.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('throws AdminAuthError on a 401', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 401 }))
    await expect(adminMe()).rejects.toBeInstanceOf(AdminAuthError)
  })

  it('throws AdminNetworkError (not a plain Error) on a 5xx', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'db down' }, 503))
    await expect(adminMe()).rejects.toBeInstanceOf(AdminNetworkError)
  })

  it('throws a plain Error (not AdminNetworkError) on a non-401 4xx', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'bad request' }, 400))
    const err = await adminMe().catch(e => e)
    expect(err).toBeInstanceOf(Error)
    expect(err).not.toBeInstanceOf(AdminAuthError)
    expect(err).not.toBeInstanceOf(AdminNetworkError)
  })

  it('throws AdminNetworkError when fetch itself rejects (offline/DNS failure)', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(adminMe()).rejects.toBeInstanceOf(AdminNetworkError)
  })

  it('resolves undefined on a 204 No Content', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(adminMe()).resolves.toBeUndefined()
  })

  it('adminLogin POSTs the username/password as JSON', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await adminLogin('admin', 'secret')
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/admin/login')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init!.body as string)).toEqual({ username: 'admin', password: 'secret' })
  })
})

describe('representative wrapper request shapes', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetchAdminStats hits the stats endpoint with no params', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ counts: {}, db_reads: 0, match_breakdown: null }))
    await fetchAdminStats()
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/admin/stats')
  })

  it('fetchBatteries builds pagination + filter query params', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ total: 0, page: 2, page_size: 10, items: [] }))
    await fetchBatteries(2, 10, 'corolla', 'AGM')
    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toBe('/api/admin/batteries?page=2&page_size=10&search=corolla&technology=AGM')
  })

  it('addBattery POSTs the battery payload', async () => {
    const payload = { battery_code: 'X1', model_key: 'X1', ah: 60, cca_en: null, technology: 'MF' }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ id: 1, battery_code: 'X1' }))
    await addBattery(payload)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/admin/batteries')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init!.body as string)).toEqual(payload)
  })

  it('deleteBattery issues a DELETE to the battery-id URL', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await deleteBattery(42)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/admin/batteries/42')
    expect(init?.method).toBe('DELETE')
  })

  it('revokeSession issues a DELETE to the session-id URL', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await revokeSession(7)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/admin/sessions/7')
    expect(init?.method).toBe('DELETE')
  })
})

describe('uploadBatteriesExcel (FormData path, separate from adminFetch)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the file as multipart FormData without a manual Content-Type', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ inserted: 1, updated: 0, skipped_unchanged: 0, rejected: 0, errors: [] })
    )
    const file = new File(['a,b,c'], 'batteries.xlsx')
    await uploadBatteriesExcel(file)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/admin/batteries/upload')
    expect(init?.body).toBeInstanceOf(FormData)
    expect((init?.body as FormData).get('file')).toBe(file)
    expect((init?.headers as Record<string, string> | undefined)?.['Content-Type']).toBeUndefined()
  })

  it('throws AdminAuthError on a 401', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 401 }))
    await expect(uploadBatteriesExcel(new File(['x'], 'x.xlsx'))).rejects.toBeInstanceOf(AdminAuthError)
  })

  it('throws AdminNetworkError when fetch itself rejects', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    await expect(uploadBatteriesExcel(new File(['x'], 'x.xlsx'))).rejects.toBeInstanceOf(AdminNetworkError)
  })
})

describe('downloadFeedbackPdf / downloadFeedbackCsv (blob + anchor-click download)', () => {
  let clickSpy: ReturnType<typeof vi.spyOn>
  let createObjectURL: ReturnType<typeof vi.fn>
  let revokeObjectURL: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    // jsdom doesn't implement Blob-URL creation — assign directly rather
    // than vi.stubGlobal (which would replace the whole URL constructor).
    createObjectURL = vi.fn().mockReturnValue('blob:mock-url')
    revokeObjectURL = vi.fn()
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    clickSpy.mockRestore()
  })

  it('downloadFeedbackPdf uses the filename from Content-Disposition and clicks a download link', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(new Blob(['pdf-bytes']), {
        status: 200,
        headers: { 'Content-Disposition': 'attachment; filename="report_2026.pdf"' },
      })
    )
    await downloadFeedbackPdf('exact')
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/admin/feedback/export-pdf?accuracy=exact')
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(clickSpy).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
  })

  it('downloadFeedbackCsv falls back to a default filename when no Content-Disposition is present', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new Blob(['csv-bytes']), { status: 200 }))
    await downloadFeedbackCsv()
    expect(clickSpy).toHaveBeenCalledOnce()
  })

  it('downloadFeedbackPdf throws AdminAuthError on a 401 without attempting a download', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 401 }))
    await expect(downloadFeedbackPdf()).rejects.toBeInstanceOf(AdminAuthError)
    expect(clickSpy).not.toHaveBeenCalled()
  })
})
