import { useState, type FormEvent } from 'react'
import { isTokenValid, storeToken } from '../api/client'
import './Login.css'

interface LoginProps {
  onLogin: () => void
}

export function Login({ onLogin }: LoginProps) {
  const [token, setTokenInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    const valid = await isTokenValid(token)

    setSubmitting(false)

    if (!valid) {
      setError('Invalid token')
      return
    }

    storeToken(token)
    onLogin()
  }

  return (
    <div className="login-screen">
      <form className="login-form" onSubmit={handleSubmit}>
        <h1>Passage Simulator</h1>
        <input
          type="password"
          placeholder="Access token"
          value={token}
          onChange={(event) => setTokenInput(event.target.value)}
          autoFocus
        />
        <button type="submit" disabled={submitting || token.length === 0}>
          {submitting ? 'Checking…' : 'Log in'}
        </button>
        {error && <p className="login-error">{error}</p>}
      </form>
    </div>
  )
}
