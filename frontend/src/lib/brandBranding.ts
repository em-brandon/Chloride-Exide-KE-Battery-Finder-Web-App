import exideMaxLogo  from '@/assets/exide-max-logo.webp'
import sparkLogo     from '@/assets/spark-logo.webp'
import powerlastLogo from '@/assets/powerlast-logo.webp'
import supremeLogo   from '@/assets/supreme-logo.webp'
import sebangLogo    from '@/assets/sebang-logo.webp'
import exideAgmLogo  from '@/assets/exide-agm-logo.webp'
import sbFloodedLogo from '@/assets/sb-flooded-logo.webp'
import exideEfbLogo  from '@/assets/exide-efb-logo.webp'
import type { BatteryRow } from './adminApi'

// Shared between AdminBatteries.tsx (brand overview tiles) and
// AdminDashboard.tsx (Battery Records card logo strip) — one battery_specs
// row doesn't map 1:1 to a marketable brand name (Chloride Exide and Exide
// Matrix each cover multiple product lines distinguished by technology), so
// resolveDisplayBrand() is the single place that logic lives.

export const BRAND_COLOR: Record<string, string> = {
  'Powerlast':          '#CC0000',
  'Exide Maxx':         '#CC0000',
  'Spark':              '#1d4ed8',
  'SB Flooded':         '#059669',
  'Chloride Exide AGM': '#7e22ce',
  'Exide AGM':          '#6366f1',
  'Supreme':            '#d97706',
  'Sebang':             '#0891b2',
}
export function brandColor(brand: string) { return BRAND_COLOR[brand] ?? '#6b7280' }

export const BRAND_LOGO: Record<string, string> = {
  'Exide Maxx':         exideMaxLogo,
  'Spark':              sparkLogo,
  'Powerlast':          powerlastLogo,
  'Supreme':            supremeLogo,
  'Sebang':             sebangLogo,
  'Chloride Exide AGM': exideAgmLogo,
  'SB Flooded':         sbFloodedLogo,
  'Exide Matrix EFB':   exideEfbLogo,
  'Exide Matrix MF':    sbFloodedLogo,
}

// Resolve DB brand → display brand.
export function resolveDisplayBrand(b: BatteryRow): string {
  const brandUp = (b.brand ?? '').toUpperCase()
  const codeUp  = (b.battery_code ?? '').toUpperCase()
  const techUp  = (b.technology ?? '').toUpperCase()
  if (brandUp.includes('MAXX') || codeUp.includes('MAXX')) return 'Exide Maxx'
  if (brandUp === 'CHLORIDE EXIDE') {
    return techUp === 'AGM' ? 'Chloride Exide AGM' : 'SB Flooded'
  }
  if (brandUp === 'EXIDE MATRIX') {
    if (techUp === 'AGM') return 'Chloride Exide AGM'
    if (techUp === 'EFB') return 'Exide Matrix EFB'
    return 'Exide Matrix MF'
  }
  return b.brand ?? 'Unknown'
}

export function groupByBrand(batteries: BatteryRow[]): Array<{ brand: string; count: number }> {
  const map = new Map<string, number>()
  for (const b of batteries) {
    const key = resolveDisplayBrand(b)
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  return Array.from(map.entries())
    .map(([brand, count]) => ({ brand, count }))
    .sort((a, b) => b.count - a.count)
}
