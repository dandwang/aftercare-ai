import { afterEach, describe, expect, it, vi } from 'vitest'

const apiBaseUrl = 'http://localhost:8000'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function loadAuth() {
  vi.resetModules()
  return import('./auth')
}

afterEach(() => {
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('authentication session', () => {
  it('logs in, persists the token for the browser session, and loads the user', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ access_token: 'test-token', token_type: 'bearer', expires_in: 1800 }))
      .mockResolvedValueOnce(jsonResponse({
        user_id: 'cbd1c0f1-39a5-471c-a0a7-90f132c00631',
        email: 'admin@example.com',
        tenant_id: 'af52ab1c-9fc9-45c6-8b9a-2e65a471f1af',
        tenant_name: 'Example Store',
        role: 'merchant_admin',
      }))
    vi.stubGlobal('fetch', fetchMock)
    const { useAuth } = await loadAuth()

    await useAuth().login('admin@example.com', 'correct-horse-battery-staple')

    expect(sessionStorage.getItem('aftercare.access-token')).toBe('test-token')
    expect(useAuth().currentUser.value?.email).toBe('admin@example.com')
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${apiBaseUrl}/api/v1/auth/login`, expect.any(Object))
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${apiBaseUrl}/api/v1/auth/me`, {
      headers: { Authorization: 'Bearer test-token' },
    })
  })

  it('clears an expired or revoked token while restoring the session', async () => {
    sessionStorage.setItem('aftercare.access-token', 'expired-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
    const { useAuth } = await loadAuth()

    await expect(useAuth().restoreSession()).resolves.toBe(false)

    expect(sessionStorage.getItem('aftercare.access-token')).toBeNull()
    expect(useAuth().isAuthenticated.value).toBe(false)
  })

  it('does not persist a token when credentials are rejected', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
    const { useAuth } = await loadAuth()

    await expect(useAuth().login('admin@example.com', 'wrong-password')).rejects.toThrow('INVALID_CREDENTIALS')

    expect(sessionStorage.getItem('aftercare.access-token')).toBeNull()
  })

  it('removes a session on logout', async () => {
    sessionStorage.setItem('aftercare.access-token', 'test-token')
    const { useAuth } = await loadAuth()

    useAuth().logout()

    expect(sessionStorage.getItem('aftercare.access-token')).toBeNull()
    expect(useAuth().isAuthenticated.value).toBe(false)
  })
})
