import { cn } from '@/lib/utils'

interface BadgeProps {
  variant?: 'exact' | 'close' | 'fallback' | 'efb' | 'agm' | 'mf' | 'sb'
  className?: string
  children: React.ReactNode
}

const variantClasses: Record<NonNullable<BadgeProps['variant']>, string> = {
  exact:    'bg-emerald-100 text-emerald-700 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800',
  close:    'bg-orange-100 text-orange-700 border border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800',
  fallback: 'bg-violet-100 text-violet-700 border border-violet-200 dark:bg-violet-900/30 dark:text-violet-400 dark:border-violet-800',
  efb:      'bg-orange-100 text-orange-700 border border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800',
  agm:      'bg-violet-100 text-violet-700 border border-violet-200 dark:bg-violet-900/30 dark:text-violet-400 dark:border-violet-800',
  mf:       'bg-gray-100  text-gray-700  border border-gray-200  dark:bg-gray-800      dark:text-gray-300      dark:border-gray-700',
  sb:       'bg-blue-100  text-blue-700  border border-blue-200  dark:bg-blue-900/30   dark:text-blue-400      dark:border-blue-800',
}

export function Badge({ variant = 'mf', className, children }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wide whitespace-nowrap',
        variantClasses[variant],
        className
      )}
    >
      {children}
    </span>
  )
}

export function techVariant(tech?: string): BadgeProps['variant'] {
  if (!tech) return 'mf'
  const t = tech.toUpperCase()
  if (t.includes('EFB')) return 'efb'
  if (t.includes('AGM')) return 'agm'
  if (t.includes('SB') || t.includes('FLOODED')) return 'sb'
  return 'mf'
}

export function matchVariant(matchType: string): BadgeProps['variant'] {
  if (matchType.toLowerCase().includes('exact')) return 'exact'
  if (matchType.toLowerCase().includes('close')) return 'close'
  return 'fallback'
}
