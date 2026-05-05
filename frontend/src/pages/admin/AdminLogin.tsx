import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { adminLogin } from '@/lib/adminApi'

export default function AdminLogin() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState<string | null>(null)
  const [loading, setLoading]   = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await adminLogin(username, password)
      navigate('/admin/dashboard', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(160deg, #f4f5f7 0%, #eef0f4 100%)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '1.5rem', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>

      {/* Brand header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '2rem' }}>
        <svg width="48" height="48" viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <rect x="4" y="18" width="48" height="28" rx="3" fill="#CC0000"/>
          <rect x="5" y="19" width="46" height="26" rx="2" fill="#f3f3f3" stroke="#CC0000" strokeWidth="1"/>
          <rect x="11" y="12" width="8" height="7" rx="1.5" fill="#CC0000"/>
          <rect x="37" y="12" width="8" height="7" rx="1.5" fill="#888888"/>
          <text x="15" y="18.5" textAnchor="middle" fontSize="6" fontWeight="bold" fill="#fff">+</text>
          <text x="41" y="18.5" textAnchor="middle" fontSize="7" fontWeight="bold" fill="#fff">−</text>
          <line x1="18" y1="21" x2="18" y2="43" stroke="#CC0000" strokeWidth="1.2" opacity="0.5"/>
          <line x1="28" y1="21" x2="28" y2="43" stroke="#CC0000" strokeWidth="1.2" opacity="0.5"/>
          <line x1="38" y1="21" x2="38" y2="43" stroke="#CC0000" strokeWidth="1.2" opacity="0.5"/>
          <circle cx="13" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
          <circle cx="23" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
          <circle cx="33" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
          <circle cx="43" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
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

      {/* Card */}
      <div style={{ width: '100%', maxWidth: '380px', background: '#ffffff', borderRadius: '16px', boxShadow: '0 4px 24px rgba(0,0,0,0.09)', border: '1px solid #e2e4e9', overflow: 'hidden' }}>

        {/* Red accent bar */}
        <div style={{ height: '4px', background: 'linear-gradient(90deg, #CC0000 0%, #990000 100%)' }} />

        <div style={{ padding: '2rem' }}>
          <h1 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)', marginBottom: '0.25rem' }}>
            Sign in
          </h1>
          <p style={{ fontSize: '0.8rem', color: 'rgba(107,114,128,0.9)', marginBottom: '1.5rem' }}>
            Restricted to authorised administrators only.
          </p>

          {error && (
            <div style={{ marginBottom: '1rem', borderRadius: '8px', background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.75rem 1rem', fontSize: '0.82rem', color: '#CC0000' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, color: 'rgba(17,24,39,0.75)', marginBottom: '0.4rem', letterSpacing: '0.02em' }}>
                Username
              </label>
              <input
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={e => setUsername(e.target.value)}
                style={{ width: '100%', borderRadius: '8px', border: '1.5px solid #e2e4e9', background: '#f9fafb', color: 'rgba(17,24,39,0.88)', padding: '0.55rem 0.85rem', fontSize: '0.875rem', outline: 'none', boxSizing: 'border-box', transition: 'border-color 0.2s' }}
                onFocus={e => (e.currentTarget.style.borderColor = '#CC0000')}
                onBlur={e  => (e.currentTarget.style.borderColor = '#e2e4e9')}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, color: 'rgba(17,24,39,0.75)', marginBottom: '0.4rem', letterSpacing: '0.02em' }}>
                Password
              </label>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                style={{ width: '100%', borderRadius: '8px', border: '1.5px solid #e2e4e9', background: '#f9fafb', color: 'rgba(17,24,39,0.88)', padding: '0.55rem 0.85rem', fontSize: '0.875rem', outline: 'none', boxSizing: 'border-box', transition: 'border-color 0.2s' }}
                onFocus={e => (e.currentTarget.style.borderColor = '#CC0000')}
                onBlur={e  => (e.currentTarget.style.borderColor = '#e2e4e9')}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{ marginTop: '0.25rem', width: '100%', borderRadius: '8px', background: loading ? '#e2e4e9' : '#CC0000', color: loading ? 'rgba(107,114,128,0.9)' : '#ffffff', border: 'none', fontWeight: 700, fontSize: '0.875rem', padding: '0.65rem', cursor: loading ? 'not-allowed' : 'pointer', transition: 'background 0.2s', letterSpacing: '0.03em' }}
              onMouseEnter={e => { if (!loading) e.currentTarget.style.background = '#990000' }}
              onMouseLeave={e => { if (!loading) e.currentTarget.style.background = '#CC0000' }}
            >
              {loading ? 'Signing in…' : 'Sign in'}
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
