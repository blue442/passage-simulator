const TOKEN_STORAGE_KEY = 'passage.token'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export class UnauthorizedError extends Error {
  constructor() {
    super('Unauthorized')
  }
}

async function request(path: string, token: string | null, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(path, { ...init, headers })

  if (response.status === 401) {
    clearStoredToken()
    throw new UnauthorizedError()
  }

  return response
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return request(path, getStoredToken(), init)
}

export async function isTokenValid(token: string): Promise<boolean> {
  try {
    const response = await request('/api/me', token)
    return response.ok
  } catch {
    return false
  }
}
