import { computed, ref } from 'vue'

export interface CurrentUser {
  user_id: string
  email: string
  tenant_id: string
  tenant_name: string
  role: string
}

interface AccessTokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

type AuthStatus = 'anonymous' | 'loading' | 'authenticated'

const tokenStorageKey = 'aftercare.access-token'
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const accessToken = ref<string | null>(sessionStorage.getItem(tokenStorageKey))
const currentUser = ref<CurrentUser | null>(null)
const status = ref<AuthStatus>('anonymous')
const initialized = ref(false)

function clearSession(): void {
  accessToken.value = null
  currentUser.value = null
  sessionStorage.removeItem(tokenStorageKey)
}

async function requestCurrentUser(token: string): Promise<CurrentUser | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) return null
    return (await response.json()) as CurrentUser
  } catch {
    return null
  }
}

export async function authenticatedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (!accessToken.value) throw new Error('INVALID_SESSION')

  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${accessToken.value}`)
  const response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers })
  if (response.status === 401) {
    clearSession()
    status.value = 'anonymous'
  }
  return response
}

async function loadCurrentUser(): Promise<boolean> {
  if (!accessToken.value) {
    clearSession()
    status.value = 'anonymous'
    return false
  }

  status.value = 'loading'
  const user = await requestCurrentUser(accessToken.value)
  if (!user) {
    clearSession()
    status.value = 'anonymous'
    return false
  }

  currentUser.value = user
  status.value = 'authenticated'
  return true
}

async function restoreSession(): Promise<boolean> {
  if (initialized.value) return status.value === 'authenticated'

  initialized.value = true
  return loadCurrentUser()
}

async function login(email: string, password: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!response.ok) throw new Error('INVALID_CREDENTIALS')

  const payload = (await response.json()) as AccessTokenResponse
  if (!payload.access_token || payload.token_type.toLowerCase() !== 'bearer') {
    throw new Error('INVALID_TOKEN_RESPONSE')
  }

  accessToken.value = payload.access_token
  sessionStorage.setItem(tokenStorageKey, payload.access_token)
  initialized.value = true
  if (!(await loadCurrentUser())) throw new Error('INVALID_SESSION')
}

function logout(): void {
  initialized.value = true
  clearSession()
  status.value = 'anonymous'
}

export function useAuth() {
  return {
    currentUser: computed(() => currentUser.value),
    isAuthenticated: computed(() => status.value === 'authenticated'),
    isLoading: computed(() => status.value === 'loading'),
    login,
    logout,
    restoreSession,
  }
}
