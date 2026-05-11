/**
 * TestUserLogin.tsx — Login/register page for test users.
 *
 * Route: /login
 * After successful login the user is redirected to / (home).
 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { loginUser, registerUser } from '@/lib/testUserApi'
import { useTestUser } from '@/lib/TestUserContext'

// ── Brand battery SVG (same as admin login) ───────────────────────────────────
function BatteryLogo() {
  const R = '#CC0000'
  return (
    <svg width="48" height="48" viewBox="0 0 24 24" fill={R} xmlns="http://www.w3.org/2000/svg">
      <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clipRule="evenodd" />
    </svg>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────
const R = '#CC0000'
const S: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(160deg,#f4f5f7 0%,#eef0f4 100%)',
    fontFamily: "'Segoe UI',system-ui,sans-serif",
    padding: '1.5rem',
  },
  card: {
    background: '#fff',
    borderRadius: 16,
    boxShadow: '0 8px 32px rgba(0,0,0,0.10)',
    padding: '2.5rem 2rem',
    width: '100%',
    maxWidth: 400,
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
  },
  header: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '0.6rem',
    textAlign: 'center',
  },
  title: { fontSize: '1.4rem', fontWeight: 800, color: '#111827', margin: 0 },
  subtitle: { fontSize: '0.8rem', color: '#6b7280', margin: 0 },
  tabs: {
    display: 'flex',
    border: '1px solid #e2e4e9',
    borderRadius: 10,
    overflow: 'hidden',
  },
  tabActive: {
    flex: 1,
    padding: '0.55rem 0',
    border: 'none',
    background: R,
    color: '#fff',
    fontWeight: 700,
    fontSize: '0.85rem',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  tabInactive: {
    flex: 1,
    padding: '0.55rem 0',
    border: 'none',
    background: 'transparent',
    color: '#6b7280',
    fontWeight: 500,
    fontSize: '0.85rem',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  label: {
    display: 'block',
    fontSize: '0.78rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    color: '#374151',
    marginBottom: '0.4rem',
  },
  input: {
    width: '100%',
    boxSizing: 'border-box',
    padding: '0.6rem 0.85rem',
    border: '1px solid #e2e4e9',
    borderRadius: 8,
    fontSize: '0.9rem',
    outline: 'none',
    transition: 'border-color 0.15s',
    fontFamily: 'inherit',
  },
  btn: {
    width: '100%',
    padding: '0.7rem',
    border: 'none',
    borderRadius: 8,
    background: R,
    color: '#fff',
    fontSize: '0.95rem',
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'background 0.15s',
    marginTop: '0.25rem',
  },
  error: {
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: 8,
    padding: '0.6rem 0.8rem',
    color: '#b91c1c',
    fontSize: '0.82rem',
  },
  success: {
    background: '#f0fdf4',
    border: '1px solid #bbf7d0',
    borderRadius: 8,
    padding: '0.6rem 0.8rem',
    color: '#15803d',
    fontSize: '0.82rem',
  },
  backLink: {
    textAlign: 'center' as const,
    fontSize: '0.8rem',
    color: '#6b7280',
  },
}

// ── Full-screen sign-in overlay ─────────────────────────────────────────────
function SigningInOverlay() {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: '#fff',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1.5rem',
    }}>
      <svg width="64" height="64" viewBox="0 0 24 24" fill="#CC0000" xmlns="http://www.w3.org/2000/svg" style={{ animation: 'loaderPulse 1.2s ease-in-out infinite' }}>
        <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clipRule="evenodd" />
      </svg>
      <span style={{ fontSize: '1.05rem', fontWeight: 600, color: '#374151', fontFamily: "'Segoe UI',system-ui,sans-serif" }}>Signing you in…</span>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function TestUserLogin() {
  const navigate = useNavigate()
  const { refresh, user, loading: authLoading } = useTestUser()

  // Already logged in — send straight to finder
  useEffect(() => {
    if (!authLoading && user) navigate('/', { replace: true })
  }, [authLoading, user, navigate])

  const [tab, setTab]               = useState<'login' | 'register'>('login')
  const [username, setUsername]     = useState('')
  const [password, setPassword]     = useState('')
  const [email, setEmail]           = useState('')
  const [error, setError]           = useState('')
  const [success, setSuccess]       = useState('')
  const [loading, setLoading]       = useState(false)

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setError(''); setSuccess('')
    if (!username.trim() || !password) { setError('Please enter username and password.'); return }
    setLoading(true)
    try {
      await loginUser(username.trim(), password)
      await refresh()
      navigate('/', { replace: true })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setError(''); setSuccess('')
    if (!username.trim() || !password) { setError('Please enter username and password.'); return }
    if (password.length < 6) { setError('Password must be at least 6 characters.'); return }
    setLoading(true)
    try {
      await registerUser(username.trim(), password, email.trim() || undefined)
      setSuccess('Account created! You can now log in.')
      setTab('login')
      setPassword('')
      setEmail('')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Registration failed.')
    } finally {
      setLoading(false)
    }
  }

  function switchTab(t: 'login' | 'register') {
    setTab(t); setError(''); setSuccess(''); setUsername(''); setPassword(''); setEmail('')
  }

  if (loading && tab === 'login') return <SigningInOverlay />

  return (
    <div style={S.page}>
      <div style={S.card}>
        {/* Header */}
        <div style={S.header}>
          <BatteryLogo />
          <h1 style={S.title}>
            CHLORIDE <span style={{ color: R }}>EXIDE</span>
          </h1>
          <p style={S.subtitle}>Battery Finder — Tester Access</p>
        </div>

        {/* Tabs */}
        <div style={S.tabs}>
          <button
            type="button"
            style={tab === 'login' ? S.tabActive : S.tabInactive}
            onClick={() => switchTab('login')}
          >Sign in</button>
          <button
            type="button"
            style={tab === 'register' ? S.tabActive : S.tabInactive}
            onClick={() => switchTab('register')}
          >Create account</button>
        </div>

        {/* Messages */}
        {error   && <div style={S.error}>{error}</div>}
        {success && <div style={S.success}>{success}</div>}

        {/* Login form */}
        {tab === 'login' && (
          <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
            <div>
              <label style={S.label}>Username</label>
              <input
                type="text"
                autoComplete="username"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="your_username"
                style={S.input}
                onFocus={e => { e.currentTarget.style.borderColor = R }}
                onBlur={e => { e.currentTarget.style.borderColor = '#e2e4e9' }}
              />
            </div>
            <div>
              <label style={S.label}>Password</label>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••"
                style={S.input}
                onFocus={e => { e.currentTarget.style.borderColor = R }}
                onBlur={e => { e.currentTarget.style.borderColor = '#e2e4e9' }}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}
              onMouseEnter={e => { if (!loading) (e.currentTarget as HTMLButtonElement).style.background = '#990000' }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = R }}
            >
              Sign in
            </button>
          </form>
        )}

        {/* Register form */}
        {tab === 'register' && (
          <form onSubmit={handleRegister} style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
            <div>
              <label style={S.label}>Username</label>
              <input
                type="text"
                autoComplete="username"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="letters, numbers, _ or -"
                style={S.input}
                onFocus={e => { e.currentTarget.style.borderColor = R }}
                onBlur={e => { e.currentTarget.style.borderColor = '#e2e4e9' }}
              />
            </div>
            <div>
              <label style={S.label}>Password</label>
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="at least 6 characters"
                style={S.input}
                onFocus={e => { e.currentTarget.style.borderColor = R }}
                onBlur={e => { e.currentTarget.style.borderColor = '#e2e4e9' }}
              />
            </div>
            <div>
              <label style={S.label}>
                Email <span style={{ textTransform: 'none', fontWeight: 400, color: '#9ca3af' }}>(optional)</span>
              </label>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                style={S.input}
                onFocus={e => { e.currentTarget.style.borderColor = R }}
                onBlur={e => { e.currentTarget.style.borderColor = '#e2e4e9' }}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}
              onMouseEnter={e => { if (!loading) (e.currentTarget as HTMLButtonElement).style.background = '#990000' }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = R }}
            >
              {loading ? 'Creating account…' : 'Create account'}
            </button>
          </form>
        )}

        <p style={S.backLink}>
          <a href="/" style={{ color: R, textDecoration: 'none', fontWeight: 600 }}>← Back to Battery Finder</a>
        </p>
      </div>
    </div>
  )
}
