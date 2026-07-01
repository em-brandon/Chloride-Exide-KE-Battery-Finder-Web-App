import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { adminMe } from '@/lib/adminApi'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<'loading' | 'ok' | 'unauth'>('loading')

  useEffect(() => {
    adminMe()
      .then(() => setStatus('ok'))
      .catch(() => setStatus('unauth'))
  }, [])

  if (status === 'loading') return null
  if (status === 'unauth') return <Navigate to="/admin/login" replace />
  return <>{children}</>
}
