import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TestUserProvider, useTestUser } from './TestUserContext'
import * as testUserApi from './testUserApi'

vi.mock('./testUserApi')

function Consumer() {
  const { user, loading, logout } = useTestUser()
  if (loading) return <div>loading</div>
  return (
    <div>
      <div>user: {user ? user.username : 'none'}</div>
      <button onClick={() => logout()}>logout</button>
    </div>
  )
}

describe('TestUserProvider', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows no user when there is no stored token, without calling fetchMe', async () => {
    vi.mocked(testUserApi.getCachedUser).mockReturnValue(null)
    vi.mocked(testUserApi.getToken).mockReturnValue(null)

    render(<TestUserProvider><Consumer /></TestUserProvider>)
    await waitFor(() => expect(screen.getByText('user: none')).toBeInTheDocument())
    expect(testUserApi.fetchMe).not.toHaveBeenCalled()
  })

  it('shows a loading state while fetchMe is in flight, then resolves the real user', async () => {
    vi.mocked(testUserApi.getCachedUser).mockReturnValue(null)
    vi.mocked(testUserApi.getToken).mockReturnValue('tok-123')
    let resolveFetchMe!: (u: testUserApi.TestUserInfo) => void
    vi.mocked(testUserApi.fetchMe).mockReturnValue(
      new Promise(resolve => { resolveFetchMe = resolve })
    )

    render(<TestUserProvider><Consumer /></TestUserProvider>)
    expect(screen.getByText('loading')).toBeInTheDocument()

    resolveFetchMe({ user_id: 1, username: 'brandon', email: null })
    await waitFor(() => expect(screen.getByText('user: brandon')).toBeInTheDocument())
  })

  it('treats a fetchMe failure as logged-out without throwing', async () => {
    vi.mocked(testUserApi.getCachedUser).mockReturnValue({ user_id: 1, username: 'brandon', email: null })
    vi.mocked(testUserApi.getToken).mockReturnValue('tok-123')
    vi.mocked(testUserApi.fetchMe).mockRejectedValue(new Error('Session expired'))

    render(<TestUserProvider><Consumer /></TestUserProvider>)
    await waitFor(() => expect(screen.getByText('user: none')).toBeInTheDocument())
  })

  it('logout() clears the user and calls logoutUser()', async () => {
    vi.mocked(testUserApi.getCachedUser).mockReturnValue(null)
    vi.mocked(testUserApi.getToken).mockReturnValue('tok-123')
    vi.mocked(testUserApi.fetchMe).mockResolvedValue({ user_id: 1, username: 'brandon', email: null })
    vi.mocked(testUserApi.logoutUser).mockResolvedValue(undefined)
    const user = userEvent.setup()

    render(<TestUserProvider><Consumer /></TestUserProvider>)
    await waitFor(() => expect(screen.getByText('user: brandon')).toBeInTheDocument())

    await user.click(screen.getByText('logout'))
    expect(testUserApi.logoutUser).toHaveBeenCalledOnce()
    await waitFor(() => expect(screen.getByText('user: none')).toBeInTheDocument())
  })
})
