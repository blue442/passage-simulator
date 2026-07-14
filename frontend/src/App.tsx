import { useEffect, useState } from 'react'
import { Login } from './components/Login'
import { MapView } from './components/MapView'
import { apiFetch, getStoredToken } from './api/client'

type AuthState = 'checking' | 'authenticated' | 'unauthenticated'

function App() {
  const [authState, setAuthState] = useState<AuthState>('checking')

  useEffect(() => {
    const token = getStoredToken()
    if (!token) {
      setAuthState('unauthenticated')
      return
    }

    apiFetch('/api/me')
      .then((response) => setAuthState(response.ok ? 'authenticated' : 'unauthenticated'))
      .catch(() => setAuthState('unauthenticated'))
  }, [])

  if (authState === 'checking') {
    return null
  }

  if (authState === 'unauthenticated') {
    return <Login onLogin={() => setAuthState('authenticated')} />
  }

  return <MapView />
}

export default App
