import { lazy, Suspense, useState, useCallback, useRef, useEffect } from 'react'
import chlorideExideLogo     from '@/assets/chloride_exide_transparent.webp'
import chlorideExideBrandLogo from '@/assets/chlorideexidebrandlogo.webp'
import { Routes, Route, Navigate } from 'react-router-dom'
import { PageLoader } from '@/components/PageLoader'
import { VehicleFinderForm } from '@/components/VehicleFinderForm'
import { MobileVehicleFinder } from '@/components/MobileVehicleFinder'
import { Moon, Sun, Settings } from 'lucide-react'
import { ProtectedRoute } from '@/components/admin/ProtectedRoute'
import { TestUserProvider, useTestUser } from '@/lib/TestUserContext'
import { TermsGate } from '@/components/TermsGate'
import { useIsMobile } from '@/lib/utils'

const AdminLogin        = lazy(() => import('@/pages/admin/AdminLogin'))
const AdminDashboard    = lazy(() => import('@/pages/admin/AdminDashboard'))
const AdminBatteries    = lazy(() => import('@/pages/admin/AdminBatteries'))
const AdminAuditLog     = lazy(() => import('@/pages/admin/AdminAuditLog'))
const AdminSessions     = lazy(() => import('@/pages/admin/AdminSessions'))
const AdminCoverage     = lazy(() => import('@/pages/admin/AdminCoverage'))
const AdminFeedback     = lazy(() => import('@/pages/admin/AdminFeedback'))
const AdminTestSessions = lazy(() => import('@/pages/admin/AdminTestSessions'))
const AdminSettings     = lazy(() => import('@/pages/admin/AdminSettings'))
const AdminDataPipeline = lazy(() => import('@/pages/admin/AdminDataPipeline'))
const TestUserLogin     = lazy(() => import('@/pages/TestUserLogin'))
const FaqModal          = lazy(() => import('@/components/FaqModal').then(m => ({ default: m.FaqModal })))
const CopyrightModal    = lazy(() => import('@/components/CopyrightModal').then(m => ({ default: m.CopyrightModal })))
const PrivacyModal      = lazy(() => import('@/components/PrivacyModal').then(m => ({ default: m.PrivacyModal })))
const BuildVersionModal = lazy(() => import('@/components/BuildVersionModal').then(m => ({ default: m.BuildVersionModal })))
const HowToUseModal     = lazy(() => import('@/components/HowToUseModal').then(m => ({ default: m.HowToUseModal })))

// ---------------------------------------------------------------------------
// Test-user gate — redirects to /login if not authenticated
// ---------------------------------------------------------------------------

function TestUserRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useTestUser()
  if (loading) return <PageLoader visible />
  if (!user)   return <Navigate to="/login" replace />
  return <>{children}</>
}

// ---------------------------------------------------------------------------
// Public finder page — extracted so App() stays clean
// ---------------------------------------------------------------------------

interface PublicAppProps {
  loaderVisible: boolean
  darkMode: boolean
  typeMode: boolean
  navEstConf: { pct: number; label: string; cls: string } | null
  confPopover: boolean
  popoverRef: React.RefObject<HTMLDivElement | null>
  onMakesLoaded: () => void
  onToggleDark: () => void
  onTypeModeChange: () => void
  onEstConfChange: (conf: { pct: number; label: string; cls: string } | null) => void
  onSetConfPopover: (v: (prev: boolean) => boolean) => void
}

function PublicApp({
  loaderVisible,
  darkMode,
  typeMode,
  navEstConf,
  confPopover,
  popoverRef,
  onMakesLoaded,
  onToggleDark,
  onTypeModeChange,
  onEstConfChange,
  onSetConfPopover,
}: PublicAppProps) {
  const isMobile = useIsMobile()
  const { user, logout } = useTestUser()
  const [faqOpen, setFaqOpen] = useState(false)
  const [copyrightOpen, setCopyrightOpen] = useState(false)
  const [privacyOpen, setPrivacyOpen] = useState(false)
  const [versionOpen, setVersionOpen] = useState(false)
  const [howToUseOpen, setHowToUseOpen] = useState(false)
  const [termsAccepted, setTermsAccepted] = useState(
    () => sessionStorage.getItem('crsp_terms_v1') === '1'
  )

  if (!termsAccepted) {
    return (
      <TermsGate
        onAccept={() => {
          sessionStorage.setItem('crsp_terms_v1', '1')
          setTermsAccepted(true)
        }}
      />
    )
  }

  return (
    <>
      <PageLoader visible={loaderVisible} />

      <div className={`page-wrapper${darkMode ? ' page-dark' : ''}`}>
        {/* ── Nav bar ── */}
        <nav className="page-nav">
          {/* Left: Brand */}
          <div className="page-nav-brand">
            <img
              src={darkMode ? chlorideExideBrandLogo : chlorideExideLogo}
              alt="Chloride Exide"
              style={{
                height: isMobile ? 44 : 52,
                width: 'auto',
                maxWidth: isMobile ? 140 : 160,
                objectFit: 'contain',
                display: 'block',
                flexShrink: 0,
                borderRadius: darkMode ? (isMobile ? 4 : 6) : 0,
              }}
            />
            <div className="page-brand-sub" style={{ alignSelf: 'center' }}>
              <span style={{ color: 'var(--red)' }}>Battery</span>{' '}
              <span style={{ color: 'var(--blue)' }}>Finder</span>
            </div>
          </div>

          {/* Center: manual mode badges — hidden on mobile (wizard has no type-mode) */}
          {typeMode && !isMobile && (
            <div className="nav-type-mode">
              <span className="nav-manual-badge"><Settings size={13} strokeWidth={1.75} style={{ marginRight: '5px', verticalAlign: 'middle' }} />Manual Mode Active</span>
              {navEstConf && navEstConf.pct > 0 && (
                <div className="nav-conf">
                  <div className="nav-conf-label-row" ref={popoverRef}>
                    <span className="nav-conf-label">Estimated Accuracy</span>
                    <button
                      className="conf-info-btn"
                      onClick={() => onSetConfPopover(v => !v)}
                      aria-label="About estimated accuracy"
                    >?</button>
                    {confPopover && (
                      <div className="conf-popover">
                        <strong>What does this score mean?</strong>
                        <p>This shows how confident we are in the battery recommendation based on what you've entered. More detail — model, year, fuel type and engine size — means a higher, more reliable score.</p>
                        <ul>
                          <li><span className="conf-dot high" />85%+ — All details provided</li>
                          <li><span className="conf-dot medium" />55–70% — Partial details</li>
                          <li><span className="conf-dot low" />40% — Make only</li>
                        </ul>
                      </div>
                    )}
                  </div>
                  <div className="bar-track nav-conf-bar">
                    <div className={navEstConf.cls} style={{ width: `${navEstConf.pct}%`, transition: 'width 0.5s ease' }} />
                  </div>
                  <span className="nav-conf-pct">{navEstConf.pct}% &mdash; {navEstConf.label}</span>
                </div>
              )}
            </div>
          )}

          {/* Right: Night mode toggle + Home + User */}
          <div className="nav-right-btns">
            {user && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151' }}>
                  {user.username}
                </span>
                <button
                  onClick={() => logout()}
                  style={{
                    padding: '0.25rem 0.65rem',
                    borderRadius: '6px',
                    border: '1px solid #e2e4e9',
                    background: '#fff',
                    cursor: 'pointer',
                    fontSize: '0.75rem',
                    color: '#6b7280',
                    fontFamily: 'inherit',
                  }}
                  title="Sign out"
                >
                  Sign out
                </button>
              </div>
            )}
            <button
              className={`nav-dark-btn nav-night-btn${darkMode ? ' active' : ''}`}
              onClick={onToggleDark}
              aria-label={darkMode ? 'Switch to day mode' : 'Switch to night mode'}
            >
              {darkMode
                ? <Sun size={16} strokeWidth={2} />
                : <Moon size={16} strokeWidth={2} />}
            </button>
            {!isMobile && (
              <a
                href="https://www.chlorideexide.com"
                target="_blank"
                rel="noopener noreferrer"
                className="nav-dark-btn nav-home-btn"
                aria-label="Go to Chloride Exide website"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" style={{ width: '1rem', height: '1rem' }}>
                  <path fillRule="evenodd" d="M9.293 2.293a1 1 0 0 1 1.414 0l7 7A1 1 0 0 1 17 11h-1v6a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6H3a1 1 0 0 1-.707-1.707l7-7Z" clipRule="evenodd" />
                </svg>
              </a>
            )}
          </div>
        </nav>

        {/* ── Finder — mobile wizard or desktop form ── */}
        {isMobile
          ? <MobileVehicleFinder darkMode={darkMode} onMakesLoaded={onMakesLoaded} />
          : <VehicleFinderForm
              onMakesLoaded={onMakesLoaded}
              typeMode={typeMode}
              onTypeModeChange={onTypeModeChange}
              onEstConfChange={onEstConfChange}
              darkMode={darkMode}
            />
        }

        {/* ── Footer ── */}
        <footer className="page-footer">
          <button className="page-footer__copyright" onClick={() => setCopyrightOpen(true)}>
            &copy; 2026 Chloride Exide Battery Finder
          </button>
          <div className="page-footer__links">
            <button className="page-footer__link" onClick={() => setPrivacyOpen(true)}>Privacy Policy</button>
            <span className="page-footer__sep" aria-hidden="true" />
            <button className="page-footer__link" onClick={() => setHowToUseOpen(true)}>How to Use</button>
            <span className="page-footer__sep" aria-hidden="true" />
            <button className="page-footer__link" onClick={() => setFaqOpen(true)}>FAQ &amp; Disclaimer</button>
            <span className="page-footer__sep" aria-hidden="true" />
            <button className="page-footer__link" onClick={() => setVersionOpen(true)}>Build Version Beta v1.1.2</button>
          </div>
        </footer>

        <HowToUseModal open={howToUseOpen} onClose={() => setHowToUseOpen(false)} />
        <FaqModal open={faqOpen} onClose={() => setFaqOpen(false)} />
        <CopyrightModal open={copyrightOpen} onClose={() => setCopyrightOpen(false)} />
        <PrivacyModal open={privacyOpen} onClose={() => setPrivacyOpen(false)} />
        <BuildVersionModal open={versionOpen} onClose={() => setVersionOpen(false)} />
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Root app — owns shared state and router
// ---------------------------------------------------------------------------

function App() {
  const [loaderVisible, setLoaderVisible] = useState(true)
  const [darkMode, setDarkMode] = useState(false)
  const [typeMode, setTypeMode] = useState(false)
  const [navEstConf, setNavEstConf] = useState<{ pct: number; label: string; cls: string } | null>(null)
  const [confPopover, setConfPopover] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!confPopover) return
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setConfPopover(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [confPopover])

  const handleMakesLoaded = useCallback(() => { setLoaderVisible(false) }, [])
  const toggleDark        = useCallback(() => { setDarkMode(d => !d) }, [])
  const handleTypeModeChange = useCallback(() => { setTypeMode(t => !t); setNavEstConf(null) }, [])
  const handleEstConfChange  = useCallback((conf: { pct: number; label: string; cls: string } | null) => {
    setNavEstConf(conf)
  }, [])

  return (
    <TestUserProvider>
    <Suspense fallback={<PageLoader visible />}>
    <Routes>
      {/* ── Public finder ── */}
      <Route path="/" element={
        <TestUserRoute>
          <PublicApp
            loaderVisible={loaderVisible}
            darkMode={darkMode}
            typeMode={typeMode}
            navEstConf={navEstConf}
            confPopover={confPopover}
            popoverRef={popoverRef}
            onMakesLoaded={handleMakesLoaded}
            onToggleDark={toggleDark}
            onTypeModeChange={handleTypeModeChange}
            onEstConfChange={handleEstConfChange}
            onSetConfPopover={setConfPopover}
          />
        </TestUserRoute>
      } />

      {/* ── Admin ── */}
      <Route path="/admin/login"     element={<AdminLogin />} />
      <Route path="/admin/dashboard" element={<ProtectedRoute><AdminDashboard /></ProtectedRoute>} />
      <Route path="/admin/batteries" element={<ProtectedRoute><AdminBatteries /></ProtectedRoute>} />
      <Route path="/admin/audit"     element={<ProtectedRoute><AdminAuditLog  /></ProtectedRoute>} />
      <Route path="/admin/sessions"      element={<ProtectedRoute><AdminSessions     /></ProtectedRoute>} />
      <Route path="/admin/coverage"      element={<ProtectedRoute><AdminCoverage     /></ProtectedRoute>} />
      <Route path="/admin/data-pipeline" element={<ProtectedRoute><AdminDataPipeline /></ProtectedRoute>} />
      <Route path="/admin/feedback"      element={<ProtectedRoute><AdminFeedback      /></ProtectedRoute>} />
      <Route path="/admin/test-sessions" element={<ProtectedRoute><AdminTestSessions /></ProtectedRoute>} />
      <Route path="/admin/settings"      element={<ProtectedRoute><AdminSettings     /></ProtectedRoute>} />
      {/* ── Test user login ── */}
      <Route path="/login" element={<TestUserLogin />} />
    </Routes>
    </Suspense>
    </TestUserProvider>
  )
}

export default App

