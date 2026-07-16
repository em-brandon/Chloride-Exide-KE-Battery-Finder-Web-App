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

// Landscape phones (e.g. an iPhone rotated sideways) can exceed `breakpoint` in width
// while still being far too short/cramped for the desktop two-column layout — catch
// those via a height-bounded query so they still get the mobile wizard.
const LANDSCAPE_PHONE_QUERY = '(max-width: 899px) and (max-height: 499px)'

export function useIsMobile(breakpoint = 600): boolean {
  const query = `(max-width: ${breakpoint - 1}px), ${LANDSCAPE_PHONE_QUERY}`
  const [mobile, setMobile] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia(query).matches
  )
  useEffect(() => {
    const mq = window.matchMedia(query)
    const handler = (e: MediaQueryListEvent) => setMobile(e.matches)
    mq.addEventListener('change', handler)
    setMobile(mq.matches)
    return () => mq.removeEventListener('change', handler)
  }, [query])
  return mobile
}
