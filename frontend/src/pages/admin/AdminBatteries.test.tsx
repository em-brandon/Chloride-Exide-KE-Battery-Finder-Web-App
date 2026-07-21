import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminBatteries from './AdminBatteries'
import { fetchBatteries, addBattery, deleteBattery, type BatteryRow } from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, fetchBatteries: vi.fn(), addBattery: vi.fn(), updateBattery: vi.fn(), deleteBattery: vi.fn() }
})

function battery(overrides: Partial<BatteryRow> = {}): BatteryRow {
  return { id: 1, battery_code: 'NS60-MF', model_key: 'NS60', ah: 60, cca_en: 480, technology: 'MF', origin: 'local', brand: 'Chloride Exide', ...overrides }
}

function renderPage(path = '/admin/batteries') {
  return render(<MemoryRouter initialEntries={[path]}><AdminBatteries /></MemoryRouter>)
}

describe('AdminBatteries — overview', () => {
  beforeEach(() => {
    vi.mocked(fetchBatteries).mockReset()
    vi.mocked(addBattery).mockReset()
    vi.mocked(deleteBattery).mockReset()
  })

  it('groups batteries by origin (local vs imported) and shows brand tile counts', async () => {
    vi.mocked(fetchBatteries).mockResolvedValue({
      total: 3, page: 1, page_size: 1000,
      items: [
        battery({ id: 1, origin: 'local', brand: 'Chloride Exide', technology: 'MF' }),
        battery({ id: 2, origin: 'local', brand: 'Chloride Exide', technology: 'MF' }),
        battery({ id: 3, origin: 'imported', brand: 'Supreme' }),
      ],
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('SB Flooded')).toBeInTheDocument())
    expect(screen.getByText('Supreme')).toBeInTheDocument()
    expect(screen.getByText('2 batteries · 1 brand')).toBeInTheDocument() // Local summary line
    expect(screen.getByText('1 batteries · 1 brand')).toBeInTheDocument() // Imported summary line
  })

  it('shows a page error when the overview load fails', async () => {
    vi.mocked(fetchBatteries).mockRejectedValue(new Error('Database unreachable'))
    renderPage()
    await waitFor(() => expect(screen.getByText('Database unreachable')).toBeInTheDocument())
  })

  it('drills into a brand tile to show that brand\'s batteries (read-only)', async () => {
    vi.mocked(fetchBatteries).mockResolvedValue({
      total: 1, page: 1, page_size: 1000,
      items: [battery({ id: 1, battery_code: 'SUP001', origin: 'imported', brand: 'Supreme' })],
    })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByText('Supreme')).toBeInTheDocument())
    await user.click(screen.getByText('Supreme'))

    await waitFor(() => expect(screen.getByText('SUP001')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
  })
})

describe('AdminBatteries — search / manage view', () => {
  beforeEach(() => {
    vi.mocked(fetchBatteries).mockReset()
    vi.mocked(addBattery).mockReset()
    vi.mocked(deleteBattery).mockReset()
  })

  it('loads the paginated table directly when ?manage=true, and shows Edit/Delete actions', async () => {
    vi.mocked(fetchBatteries).mockResolvedValue({
      total: 1, page: 1, page_size: 50,
      items: [battery({ id: 5, battery_code: 'NS70-MF' })],
    })
    renderPage('/admin/batteries?manage=true')
    await waitFor(() => expect(screen.getByText('NS70-MF')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('adds a battery through the Add Battery form', async () => {
    vi.mocked(fetchBatteries).mockResolvedValue({ total: 0, page: 1, page_size: 50, items: [] })
    vi.mocked(addBattery).mockResolvedValue({ id: 9, battery_code: 'NEW001' })
    const user = userEvent.setup()
    const { container } = renderPage('/admin/batteries?manage=true')

    await waitFor(() => expect(screen.getByRole('button', { name: /add battery/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /add battery/i }))

    // BatteryForm's field labels aren't htmlFor-associated with their
    // inputs — select the modal's <form> inputs by DOM order instead:
    // Battery Code, Model Key, Ah, CCA EN, Technology.
    const form = container.querySelector('form') as HTMLFormElement
    const [codeInput, modelInput, ahInput, , techInput] = form.querySelectorAll('input')

    await user.type(codeInput, 'new001')
    await user.type(modelInput, 'new')
    await user.type(ahInput, '55')
    await user.type(techInput, 'mf')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    // BatteryForm uppercases/trims code, model_key, technology before saving.
    expect(addBattery).toHaveBeenCalledWith({
      battery_code: 'NEW001', model_key: 'NEW', ah: 55, cca_en: null, technology: 'MF',
    })
  })

  it('deletes a battery after confirming the browser confirm dialog', async () => {
    vi.mocked(fetchBatteries).mockResolvedValue({
      total: 1, page: 1, page_size: 50,
      items: [battery({ id: 7, battery_code: 'DEL001' })],
    })
    vi.mocked(deleteBattery).mockResolvedValue(undefined)
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderPage('/admin/batteries?manage=true')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(confirmSpy).toHaveBeenCalled()
    expect(deleteBattery).toHaveBeenCalledWith(7)
    confirmSpy.mockRestore()
  })

  it('does not delete when the confirm dialog is dismissed', async () => {
    vi.mocked(fetchBatteries).mockResolvedValue({
      total: 1, page: 1, page_size: 50,
      items: [battery({ id: 7, battery_code: 'DEL001' })],
    })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderPage('/admin/batteries?manage=true')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(deleteBattery).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })
})
