import { useState, useCallback } from 'react'
import { PageLoader } from '@/components/PageLoader'
import { VehicleFinderForm } from '@/components/VehicleFinderForm'
import { Battery, Moon, Sun } from 'lucide-react'

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('theme')
    if (saved) return saved === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  const toggle = useCallback(() => {
    setDark(d => {
      const next = !d
      document.documentElement.classList.toggle('dark', next)
      localStorage.setItem('theme', next ? 'dark' : 'light')
      return next
    })
  }, [])

  // Apply class on initial load
  useState(() => {
    document.documentElement.classList.toggle('dark', dark)
  })

  return { dark, toggle }
}

function App() {
  const { dark, toggle } = useDarkMode()
  const [loaderVisible, setLoaderVisible] = useState(true)

  const handleMakesLoaded = useCallback(() => {
    setLoaderVisible(false)
  }, [])

  return (
    <>
      <PageLoader visible={loaderVisible} />

      <div className="min-h-screen bg-background transition-colors duration-300">
        {/* Header */}
        <header className="border-b border-border bg-[#cc0000] text-white shadow-sm">
          <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Battery size={24} strokeWidth={1.5} />
              <div>
                <div className="font-bold text-sm leading-tight">Chloride Exide</div>
                <div className="text-[0.65rem] opacity-80 leading-tight tracking-wide uppercase">
                  Battery Finder
                </div>
              </div>
            </div>
            <button
              onClick={toggle}
              aria-label="Toggle dark mode"
              className="rounded-full p-2 hover:bg-white/10 transition-colors"
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>

        {/* Main content */}
        <main className="max-w-3xl mx-auto px-4 py-8">
          {/* Hero text */}
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-foreground">Find the right battery</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Select your vehicle below to get a personalised battery recommendation.
            </p>
          </div>

          {/* Finder card */}
          <div className="rounded-xl border border-border bg-card shadow-md p-6">
            <VehicleFinderForm onMakesLoaded={handleMakesLoaded} />
          </div>
        </main>

        <footer className="text-center text-xs text-muted-foreground py-6 border-t border-border mt-auto">
          Chloride Exide Battery Finder &mdash; Data sourced from CRSP dataset
        </footer>
      </div>
    </>
  )
}

export default App

