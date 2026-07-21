import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  getToken,
  setToken,
  clearToken,
  getCachedUser,
  registerUser,
  loginUser,
  logoutUser,
  fetchMe,
} from './testUserApi'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

describe('token / cached-user localStorage helpers', () => {
  beforeEach(() => localStorage.clear())

  it('getToken returns null when nothing is stored', () => {
    expect(getToken()).toBeNull()
  })

  it('setToken then getToken round-trips', () => {
    setToken('tok-123')
    expect(getToken()).toBe('tok-123')
  })

  it('clearToken removes both the token and the cached user', () => {
    setToken('tok-123')
    localStorage.setItem('test_user_info', JSON.stringify({ user_id: 1, username: 'a', email: null }))
    clearToken()
    expect(getToken()).toBeNull()
    expect(getCachedUser()).toBeNull()
  })

  it('getCachedUser returns null (not throw) on corrupt JSON', () => {
    localStorage.setItem('test_user_info', '{not json')
    expect(getCachedUser()).toBeNull()
  })
})

describe('registerUser / loginUser / logoutUser / fetchMe', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    localStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('registerUser POSTs username/password/email and returns the parsed body', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ user_id: 1, username: 'brandon' }))
    await expect(registerUser('brandon', 'hunter2', 'b@example.com')).resolves.toEqual({ user_id: 1, username: 'brandon' })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/auth/register')
    expect(JSON.parse(init!.body as string)).toEqual({ username: 'brandon', password: 'hunter2', email: 'b@example.com' })
  })

  it('loginUser stores the token and caches the user on success', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ token: 'tok-abc', username: 'brandon', user_id: 1, expires_at: '2027-01-01' })
    )
    await loginUser('brandon', 'hunter2')
    expect(getToken()).toBe('tok-abc')
    expect(getCachedUser()).toEqual({ user_id: 1, username: 'brandon', email: null })
  })

  it('loginUser rejects and stores nothing on a failed login', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401))
    await expect(loginUser('brandon', 'wrong')).rejects.toThrow('Invalid credentials')
    expect(getToken()).toBeNull()
  })

  it('logoutUser calls the logout endpoint with the bearer token and always clears local state', async () => {
    setToken('tok-abc')
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await logoutUser()
    expect(getToken()).toBeNull()
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/auth/logout')
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer tok-abc')
  })

  it('logoutUser clears local state even when the network call fails', async () => {
    setToken('tok-abc')
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('network down'))
    await logoutUser()
    expect(getToken()).toBeNull()
  })

  it('logoutUser is a no-op fetch-wise when there is no token', async () => {
    await logoutUser()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('fetchMe throws without calling fetch when there is no token', async () => {
    await expect(fetchMe()).rejects.toThrow('Not authenticated')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('fetchMe clears the token and throws "Session expired" on a 401', async () => {
    setToken('tok-abc')
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 401 }))
    await expect(fetchMe()).rejects.toThrow('Session expired')
    expect(getToken()).toBeNull()
  })

  it('fetchMe caches and returns the user on success', async () => {
    setToken('tok-abc')
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ user_id: 1, username: 'brandon', email: null }))
    await expect(fetchMe()).resolves.toEqual({ user_id: 1, username: 'brandon', email: null })
    expect(getCachedUser()).toEqual({ user_id: 1, username: 'brandon', email: null })
  })
})
