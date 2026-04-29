import { Battery } from 'lucide-react'

interface PageLoaderProps {
  visible: boolean
}

export function PageLoader({ visible }: PageLoaderProps) {
  if (!visible) return null

  return (
    <div
      aria-label="Loading"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-white dark:bg-[#0f1117] transition-opacity duration-500"
    >
      <div className="relative">
        <Battery
          size={64}
          className="text-[#cc0000] animate-pulse"
          strokeWidth={1.5}
        />
      </div>
      <p className="mt-4 text-sm font-semibold text-[#cc0000] tracking-widest uppercase">
        Loading…
      </p>
    </div>
  )
}
