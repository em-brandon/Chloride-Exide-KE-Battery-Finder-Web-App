import { useState } from 'react'
import { LockClosedIcon } from '@heroicons/react/24/solid'
import { api } from '../lib/api'
import chlorideExideLogo from '@/assets/chloride_exide_transparent.png'

const R = '#CC0000'

interface Props {
  onLogin: (username: string) => void
}

export function LoginPage({ onLogin }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const r = await api.login(username, password)
      onLogin(r.username)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(135deg, #f8f9fb 0%, #eef0f4 100%)',
      fontFamily: "'Segoe UI', system-ui, sans-serif",
    }}>
      <form onSubmit={handleSubmit} style={{
        background: '#fff', borderRadius: 20,
        border: '1px solid #e2e4e9',
        boxShadow: '0 8px 40px rgba(0,0,0,0.10)',
        padding: '2.5rem 2.25rem', width: 360,
        display: 'flex', flexDirection: 'column', gap: '1.25rem',
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', justifyContent: 'center', paddingBottom: '0.25rem' }}>
          <img src={chlorideExideLogo} alt="Chloride Exide"
            style={{ height: 52, width: 'auto', objectFit: 'contain' }} />
        </div>

        {/* Title */}
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontWeight: 800, fontSize: '1.2rem', color: '#111827' }}>Pipeline Dashboard</div>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
            fontSize: '0.78rem', color: '#6b7280', marginTop: 4,
          }}>
            <LockClosedIcon style={{ width: 13, height: 13 }} />
            Admin Access Only
          </div>
        </div>

        <div style={{ height: 1, background: '#f1f3f5' }} />

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151' }}>Username</label>
          <input
            value={username} onChange={e => setUsername(e.target.value)}
            required autoFocus
            style={{
              padding: '0.6rem 0.85rem', borderRadius: 10,
              border: '1.5px solid #d1d5db', fontSize: '0.9rem',
              outline: 'none', transition: 'border-color 0.15s',
            }}
            onFocus={e => (e.target.style.borderColor = R)}
            onBlur={e => (e.target.style.borderColor = '#d1d5db')}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151' }}>Password</label>
          <input
            type="password"
            value={password} onChange={e => setPassword(e.target.value)}
            required
            style={{
              padding: '0.6rem 0.85rem', borderRadius: 10,
              border: '1.5px solid #d1d5db', fontSize: '0.9rem',
              outline: 'none', transition: 'border-color 0.15s',
            }}
            onFocus={e => (e.target.style.borderColor = R)}
            onBlur={e => (e.target.style.borderColor = '#d1d5db')}
          />
        </div>

        {error && (
          <div style={{
            fontSize: '0.78rem', color: R,
            background: '#fff5f5', border: '1px solid #fecaca',
            borderRadius: 10, padding: '0.55rem 0.85rem',
          }}>
            {error}
          </div>
        )}

        <button type="submit" disabled={loading} style={{
          background: loading ? '#e5e7eb' : R,
          color: loading ? '#9ca3af' : '#fff',
          border: 'none', borderRadius: 10,
          padding: '0.7rem', fontWeight: 700, fontSize: '0.9rem',
          cursor: loading ? 'not-allowed' : 'pointer',
          transition: 'background 0.15s',
        }}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
