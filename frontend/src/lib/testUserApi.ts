/**
 * testUserApi.ts — Auth calls for test users on the public finder.
 *
 * Token lifecycle:
 *   - Stored in localStorage under TOKEN_KEY
 *   - Sent as `Authorization: Bearer <token>` header on feedback submissions
 *   - Cleared on logout or 401 response
 */

const TOKEN_KEY  = 'test_user_token'
const USER_KEY   = 'test_user_info'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TestUserInfo {
  user_id:  number
  username: string
  email:    string | null
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getCachedUser(): TestUserInfo | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as TestUserInfo) : null
  } catch {
    return null
  }
}

function cacheUser(info: TestUserInfo): void {
  localStorage.setItem(USER_KEY, JSON.stringify(info))
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function handleAuth<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export async function registerUser(
  username: string,
  password: string,
  email?: string,
): Promise<{ user_id: number; username: string }> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, email: email || undefined }),
  })
  return handleAuth(res)
}

export async function loginUser(
  username: string,
  password: string,
): Promise<{ token: string; username: string; user_id: number; expires_at: string }> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await handleAuth<{
    token: string; username: string; user_id: number; expires_at: string
  }>(res)
  setToken(data.token)
  cacheUser({ user_id: data.user_id, username: data.username, email: null })
  return data
}

export async function logoutUser(): Promise<void> {
  const token = getToken()
  if (token) {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {/* fire and forget */})
  }
  clearToken()
}

export async function fetchMe(): Promise<TestUserInfo> {
  const token = getToken()
  if (!token) throw new Error('Not authenticated')
  const res = await fetch('/api/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.status === 401) {
    clearToken()
    throw new Error('Session expired')
  }
  const data = await handleAuth<TestUserInfo>(res)
  cacheUser(data)
  return data
}
