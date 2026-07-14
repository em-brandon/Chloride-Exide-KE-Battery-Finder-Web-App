/**
 * TestUserContext — provides the current logged-in test user
 * to the entire public app tree.
 */

import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'
import { getCachedUser, fetchMe, logoutUser, getToken } from '@/lib/testUserApi'
import type { TestUserInfo } from '@/lib/testUserApi'

interface TestUserContextValue {
  user:    TestUserInfo | null
  loading: boolean
  logout:  () => Promise<void>
  refresh: () => Promise<void>
}

const TestUserContext = createContext<TestUserContextValue>({
  user: null, loading: true, logout: async () => {}, refresh: async () => {},
})

export function useTestUser() {
  return useContext(TestUserContext)
}

export function TestUserProvider({ children }: { children: ReactNode }) {
  const [user, setUser]       = useState<TestUserInfo | null>(getCachedUser)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const token = getToken()
    if (!token) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const info = await fetchMe()
      setUser(info)
    } catch {
      // fetchMe() itself clears the stored token when the failure is a
      // genuine 401 (session expired/revoked) — for anything else (a
      // transient network blip, maintenance mode) the token stays put so a
      // real retry can still succeed, rather than silently logging the
      // user out of a still-valid session.
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    await logoutUser()
    setUser(null)
  }, [])

  return (
    <TestUserContext.Provider value={{ user, loading, logout, refresh }}>
      {children}
    </TestUserContext.Provider>
  )
}
