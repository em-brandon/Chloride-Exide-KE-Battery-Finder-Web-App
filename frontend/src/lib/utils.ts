import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { useState, useEffect } from 'react'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Strip a redundant make prefix from a model name (e.g. make="BMW", model="BMW 320i" → "320i"). */
export function stripMakePrefix(make: string | null, model: string | null): string {
  if (!make || !model) return model ?? ''
  const prefix = make.toLowerCase() + ' '
  return model.toLowerCase().startsWith(prefix) ? model.slice(prefix.length) : model
}

export function useIsMobile(breakpoint = 600): boolean {
  const [mobile, setMobile] = useState(() =>
    typeof window !== 'undefined' && window.innerWidth < breakpoint
  )
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const handler = (e: MediaQueryListEvent) => setMobile(e.matches)
    mq.addEventListener('change', handler)
    setMobile(mq.matches)
    return () => mq.removeEventListener('change', handler)
  }, [breakpoint])
  return mobile
}
