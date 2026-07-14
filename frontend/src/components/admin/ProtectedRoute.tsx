import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { adminMe, AdminNetworkError } from '@/lib/adminApi'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<'loading' | 'ok' | 'unauth' | 'unreachable'>('loading')

  useEffect(() => {
    adminMe()
      .then(() => setStatus('ok'))
      .catch(err => setStatus(err instanceof AdminNetworkError ? 'unreachable' : 'unauth'))
  }, [])

  if (status === 'loading') return null

  if (status === 'unreachable') {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: '0.75rem',
        fontFamily: "'Segoe UI', system-ui, sans-serif", padding: '1.5rem', textAlign: 'center',
      }}>
        <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)' }}>
          The server is temporarily unavailable
        </div>
        <div style={{ fontSize: '0.85rem', color: 'rgba(107,114,128,0.9)', maxWidth: 360 }}>
          We couldn't reach the backend. This usually resolves itself in a minute — please try again shortly.
        </div>
        <button
          onClick={() => window.location.reload()}
          style={{
            marginTop: '0.5rem', borderRadius: '8px', background: '#CC0000', color: '#fff',
            border: 'none', fontWeight: 700, fontSize: '0.85rem', padding: '0.55rem 1.2rem', cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>
    )
  }

  if (status === 'unauth') return <Navigate to="/admin/login" replace />
  return <>{children}</>
}
