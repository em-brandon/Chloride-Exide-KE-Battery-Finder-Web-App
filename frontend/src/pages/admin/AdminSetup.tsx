import { useState, useEffect, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBootstrapStatus, bootstrapAdmin } from '@/lib/adminApi'

const INPUT_STYLE: React.CSSProperties = {
  width: '100%', borderRadius: '8px', border: '1.5px solid #e2e4e9', background: '#f9fafb',
  color: 'rgba(17,24,39,0.88)', padding: '0.55rem 0.85rem', fontSize: '0.875rem', outline: 'none',
  boxSizing: 'border-box', transition: 'border-color 0.2s',
}

export default function AdminSetup() {
  const navigate = useNavigate()
  const [checking, setChecking] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [bootstrapToken, setBootstrapToken] = useState('')
  const [error, setError]     = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Defense in depth on top of the backend's own 403 — once an admin
  // exists there's no reason to show this page at all.
  useEffect(() => {
    getBootstrapStatus()
      .then(r => { if (!r.needs_setup) navigate('/admin/login', { replace: true }) })
      .catch(() => {})
      .finally(() => setChecking(false))
  }, [navigate])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setLoading(true)
    try {
      await bootstrapAdmin(username, password, bootstrapToken)
      navigate('/admin/login', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed')
    } finally {
      setLoading(false)
    }
  }

  if (checking) return null

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(160deg, #f4f5f7 0%, #eef0f4 100%)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '1.5rem', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '2rem' }}>
        <svg width="48" height="48" viewBox="0 0 24 24" fill="#CC0000" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clipRule="evenodd" />
        </svg>
        <div>
          <div style={{ fontSize: '1.25rem', fontWeight: 800, letterSpacing: '0.02em', color: 'rgba(17,24,39,0.88)', lineHeight: 1 }}>
            CHLORIDE <span style={{ color: '#CC0000' }}>EXIDE</span>
          </div>
          <div style={{ fontSize: '0.65rem', fontWeight: 600, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.9)', marginTop: '0.2rem' }}>
            Battery Finder · Admin
          </div>
        </div>
      </div>

      <div style={{ width: '100%', maxWidth: '380px', background: '#ffffff', borderRadius: '16px', boxShadow: '0 4px 24px rgba(0,0,0,0.09)', border: '1px solid #e2e4e9', overflow: 'hidden' }}>
        <div style={{ height: '4px', background: 'linear-gradient(90deg, #CC0000 0%, #990000 100%)' }} />

        <div style={{ padding: '2rem' }}>
          <h1 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)', marginBottom: '0.25rem' }}>
            Set up the first admin account
          </h1>
          <p style={{ fontSize: '0.8rem', color: 'rgba(107,114,128,0.9)', marginBottom: '1.5rem' }}>
            This one-time setup only works before any admin account exists. Ask whoever deployed this app for the bootstrap token.
          </p>

          {error && (
            <div style={{ marginBottom: '1rem', borderRadius: '8px', background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.75rem 1rem', fontSize: '0.82rem', color: '#CC0000' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, color: 'rgba(17,24,39,0.75)', marginBottom: '0.4rem' }}>
                Username
              </label>
              <input
                type="text" autoComplete="username" required
                value={username} onChange={e => setUsername(e.target.value)}
                style={INPUT_STYLE}
                onFocus={e => (e.currentTarget.style.borderColor = '#CC0000')}
                onBlur={e => (e.currentTarget.style.borderColor = '#e2e4e9')}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, color: 'rgba(17,24,39,0.75)', marginBottom: '0.4rem' }}>
                Password
              </label>
              <input
                type="password" autoComplete="new-password" required minLength={8}
                value={password} onChange={e => setPassword(e.target.value)}
                style={INPUT_STYLE}
                onFocus={e => (e.currentTarget.style.borderColor = '#CC0000')}
                onBlur={e => (e.currentTarget.style.borderColor = '#e2e4e9')}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, color: 'rgba(17,24,39,0.75)', marginBottom: '0.4rem' }}>
                Confirm password
              </label>
              <input
                type="password" autoComplete="new-password" required minLength={8}
                value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)}
                style={INPUT_STYLE}
                onFocus={e => (e.currentTarget.style.borderColor = '#CC0000')}
                onBlur={e => (e.currentTarget.style.borderColor = '#e2e4e9')}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, color: 'rgba(17,24,39,0.75)', marginBottom: '0.4rem' }}>
                Bootstrap token
              </label>
              <input
                type="password" required
                value={bootstrapToken} onChange={e => setBootstrapToken(e.target.value)}
                style={INPUT_STYLE}
                onFocus={e => (e.currentTarget.style.borderColor = '#CC0000')}
                onBlur={e => (e.currentTarget.style.borderColor = '#e2e4e9')}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{ marginTop: '0.25rem', width: '100%', borderRadius: '8px', background: loading ? '#e2e4e9' : '#CC0000', color: loading ? 'rgba(107,114,128,0.9)' : '#ffffff', border: 'none', fontWeight: 700, fontSize: '0.875rem', padding: '0.65rem', cursor: loading ? 'not-allowed' : 'pointer', transition: 'background 0.2s', letterSpacing: '0.03em' }}
              onMouseEnter={e => { if (!loading) e.currentTarget.style.background = '#990000' }}
              onMouseLeave={e => { if (!loading) e.currentTarget.style.background = '#CC0000' }}
            >
              {loading ? 'Creating…' : 'Create admin account'}
            </button>
          </form>
        </div>
      </div>

      <p style={{ marginTop: '1.5rem', fontSize: '0.72rem', color: 'rgba(107,114,128,0.7)' }}>
        © 2026 Chloride Exide · Battery Finder Admin
      </p>
    </div>
  )
}
