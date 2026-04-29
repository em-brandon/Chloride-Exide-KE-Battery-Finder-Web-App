import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

interface ConfidenceBarProps {
  value: number   // 0–100
  className?: string
}

export function ConfidenceBar({ value, className }: ConfidenceBarProps) {
  const [width, setWidth] = useState(0)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    // Start at 0, animate to target on next paint
    setWidth(0)
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = requestAnimationFrame(() => setWidth(value))
    })
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [value])

  const colorClass =
    value === 100 ? 'bg-emerald-400' :
    value >= 60   ? 'bg-orange-400'  :
                    'bg-violet-400'

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span className="font-medium">Match Confidence</span>
        <span className="font-semibold tabular-nums">{value}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-[width] duration-700 ease-out', colorClass)}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  )
}
