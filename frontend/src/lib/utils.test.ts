import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { cn, stripMakePrefix, useIsMobile } from './utils'

describe('cn', () => {
  it('merges class names and resolves tailwind conflicts', () => {
    expect(cn('px-2', 'py-1')).toBe('px-2 py-1')
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })

  it('drops falsy values', () => {
    expect(cn('a', false, null, undefined, 'b')).toBe('a b')
  })
})

describe('stripMakePrefix', () => {
  it('strips a matching make prefix, case-insensitively', () => {
    expect(stripMakePrefix('BMW', 'BMW 320i')).toBe('320i')
    expect(stripMakePrefix('bmw', 'BMW 320i')).toBe('320i')
  })

  it('leaves the model untouched (original casing) when it has no make prefix', () => {
    expect(stripMakePrefix('Toyota', 'Corolla')).toBe('Corolla')
  })

  it('handles null make or model', () => {
    expect(stripMakePrefix(null, 'Corolla')).toBe('Corolla')
    expect(stripMakePrefix('Toyota', null)).toBe('')
    expect(stripMakePrefix(null, null)).toBe('')
  })
})

describe('useIsMobile', () => {
  function mockMatchMedia(matches: boolean) {
    const listeners: Array<(e: MediaQueryListEvent) => void> = []
    const mql = {
      matches,
      addEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => listeners.push(cb),
      removeEventListener: vi.fn(),
    }
    window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia
    return { mql, fire: (next: boolean) => {
      mql.matches = next
      listeners.forEach(cb => cb({ matches: next } as MediaQueryListEvent))
    } }
  }

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('reflects the initial matchMedia state', () => {
    mockMatchMedia(true)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(true)
  })

  it('updates when the media query change fires', () => {
    const { fire } = mockMatchMedia(false)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)
    act(() => fire(true))
    expect(result.current).toBe(true)
  })
})
