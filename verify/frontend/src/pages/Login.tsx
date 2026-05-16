import { useState } from 'react'
import { Shield, LogIn, AlertCircle } from 'lucide-react'
import Card, { CardBody, CardHeader } from '../components/Card'
import * as api from '../api'

export default function Login() {
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await api.adminLogin(password.trim())
      window.location.assign('/')
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-tron-900 flex items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="w-12 h-12 rounded-xl bg-accent flex items-center justify-center">
            <Shield className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white">Tron Admin</h1>
          <p className="text-tron-400 text-sm max-w-sm">
            Sign in with the vault <span className="text-tron-300">auth/admin-password</span> when set, otherwise the
            <span className="text-tron-300"> master API key</span> (same value as for automation).
          </p>
        </div>

        <Card>
          <CardHeader>
            <span className="text-sm font-medium text-white">Sign in</span>
          </CardHeader>
          <CardBody>
            <form onSubmit={handleSubmit} className="space-y-4">
              {err && (
                <div className="flex items-start gap-2 text-sm text-amber-400/90">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{err}</span>
                </div>
              )}
              <div>
                <label htmlFor="pw" className="block text-xs text-tron-500 mb-1.5 uppercase tracking-wide">
                  Password
                </label>
                <input
                  id="pw"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className="w-full bg-tron-700 border border-tron-600 rounded-lg px-3 py-2.5 text-sm text-white placeholder-tron-500 focus:outline-none focus:border-accent font-mono"
                  placeholder="Admin password or master key"
                  disabled={busy}
                />
              </div>
              <button
                type="submit"
                disabled={busy || !password.trim()}
                className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-accent hover:bg-accent-dark disabled:opacity-50 text-white text-sm font-medium transition-colors"
              >
                <LogIn className="w-4 h-4" />
                {busy ? 'Signing in…' : 'Sign in'}
              </button>
            </form>
          </CardBody>
        </Card>

        <p className="text-center text-xs text-tron-600">
          Session cookie is httpOnly. Optional <span className="font-mono">X-API-Key</span> in Settings is for scripts
          and MCP only.
        </p>
      </div>
    </div>
  )
}
