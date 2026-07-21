import { describe, it, expect } from 'vitest'
import { brandColor, resolveDisplayBrand, groupByBrand } from './brandBranding'
import type { BatteryRow } from './adminApi'

function battery(overrides: Partial<BatteryRow> = {}): BatteryRow {
  return {
    id: 1,
    battery_code: 'X',
    model_key: 'X',
    ah: 60,
    cca_en: null,
    technology: 'MF',
    origin: null,
    brand: null,
    ...overrides,
  }
}

describe('brandColor', () => {
  it('returns the mapped color for a known brand', () => {
    expect(brandColor('Powerlast')).toBe('#CC0000')
  })

  it('falls back to a neutral gray for an unknown brand', () => {
    expect(brandColor('Some Unknown Brand')).toBe('#6b7280')
  })
})

describe('resolveDisplayBrand', () => {
  it('detects Exide Maxx from the brand field', () => {
    expect(resolveDisplayBrand(battery({ brand: 'Exide Maxx Pro' }))).toBe('Exide Maxx')
  })

  it('detects Exide Maxx from the battery_code when brand does not say so', () => {
    expect(resolveDisplayBrand(battery({ brand: 'Something Else', battery_code: 'MAXX001' }))).toBe('Exide Maxx')
  })

  it('splits Chloride Exide into AGM vs SB Flooded by technology', () => {
    expect(resolveDisplayBrand(battery({ brand: 'Chloride Exide', technology: 'AGM' }))).toBe('Chloride Exide AGM')
    expect(resolveDisplayBrand(battery({ brand: 'Chloride Exide', technology: 'MF' }))).toBe('SB Flooded')
  })

  it('splits Exide Matrix into AGM / EFB / MF by technology', () => {
    expect(resolveDisplayBrand(battery({ brand: 'Exide Matrix', technology: 'AGM' }))).toBe('Chloride Exide AGM')
    expect(resolveDisplayBrand(battery({ brand: 'Exide Matrix', technology: 'EFB' }))).toBe('Exide Matrix EFB')
    expect(resolveDisplayBrand(battery({ brand: 'Exide Matrix', technology: 'MF' }))).toBe('Exide Matrix MF')
  })

  it('passes through any other brand unchanged', () => {
    expect(resolveDisplayBrand(battery({ brand: 'Supreme' }))).toBe('Supreme')
  })

  it('falls back to Unknown when brand is null', () => {
    expect(resolveDisplayBrand(battery({ brand: null }))).toBe('Unknown')
  })
})

describe('groupByBrand', () => {
  it('counts batteries per resolved display brand, sorted descending by count', () => {
    const rows = [
      battery({ brand: 'Supreme' }),
      battery({ brand: 'Chloride Exide', technology: 'AGM' }),
      battery({ brand: 'Chloride Exide', technology: 'MF' }),
      battery({ brand: 'Chloride Exide', technology: 'MF' }),
    ]
    // Ties keep Map insertion order (first-seen) — Supreme was inserted
    // before Chloride Exide AGM, both count 1, SB Flooded wins on count.
    expect(groupByBrand(rows)).toEqual([
      { brand: 'SB Flooded', count: 2 },
      { brand: 'Supreme', count: 1 },
      { brand: 'Chloride Exide AGM', count: 1 },
    ])
  })

  it('returns an empty array for no batteries', () => {
    expect(groupByBrand([])).toEqual([])
  })
})
