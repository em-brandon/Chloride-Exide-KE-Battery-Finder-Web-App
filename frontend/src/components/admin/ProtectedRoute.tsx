import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { adminMe, AdminAuthError } from '@/lib/adminApi'

interface Props {
  children: React.ReactNode
}

/**
 * Wraps any admin page. Calls GET /api/admin/me to verify the session
 * cookie is still valid. Redirects to /admin/login on 401.
 */
export function ProtectedRoute({ children }: Props) {
  const [status, setStatus] = useState<'loading' | 'ok' | 'unauth'>('loading')

  useEffect(() => {
    adminMe()
      .then(() => setStatus('ok'))
      .catch((err) => {
        if (err instanceof AdminAuthError) setStatus('unauth')
        else setStatus('unauth') // treat any error as unauth to be safe
      })
  }, [])

  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center min-h-screen text-sm text-gray-500">
        Checking session…
      </div>
    )
  }

  if (status === 'unauth') {
    return <Navigate to="/admin/login" replace />
  }

  return <>{children}</>
}
