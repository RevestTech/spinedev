import { useState } from 'react'
import { Shield, LogIn, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react'
import Card, { CardBody, CardHeader } from '../components/Card'
import * as api from '../api'


/**
 * Map API error → user-facing copy.
 *
 * The API throws ``Error("<status> <statusText>: <body>")`` from
 * ``request()``. The body is JSON like ``{"detail": "Invalid credentials"}``
 * which is fine for a debugger but useless for a real user. This function
 * picks the human-readable surface for the common cases and falls back
 * to a generic message; the raw error stays available behind the
 * "Show technical details" toggle so an operator can still see it
 * without us silently swallowing the real failure.
 */
function friendlyLoginError(raw: string): { headline: string; hint?: string } {
  const m = raw.match(/^(\d{3})\s/)
  const status = m ? parseInt(m[1], 10) : 0

  if (status === 401 || status === 403 || /invalid credentials/i.test(raw)) {
    return {
      headline: "That password didn't work.",
      hint:
        "Check the value in your vault under tron/auth/admin-password " +
        "(or the master API key, if no admin password is set).",
    }
  }
  if (status === 429) {
    return {
      headline: 'Too many attempts. Wait a minute and try again.',
    }
  }
  if (status >= 500) {
    return {
      headline: "We couldn't reach the Tron API.",
      hint:
        'Confirm the API container is running (docker compose ps) and ' +
        'that nginx is healthy.',
    }
  }
  if (status === 0 && /networkerror|failed to fetch/i.test(raw)) {
    return {
      headline: 'Browser could not reach the Tron API.',
      hint:
        'Most often this is the dev TLS cert not trusted yet — ' +
        'see docs/security/TLS_RUNBOOK.md.',
    }
  }
  return { headline: 'Sign-in failed. See the details below.' }
}


export default function Login() {
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setShowDetails(false)
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

  const friendly = err ? friendlyLoginError(err) : null
  const apiOrigin = typeof window !== 'undefined'
    ? `${window.location.origin}/api`
    : '/api'

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
              {friendly && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
                  <div className="flex items-start gap-2 text-sm text-amber-300">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <div className="font-medium">{friendly.headline}</div>
                      {friendly.hint && (
                        <div className="text-xs text-amber-200/80">{friendly.hint}</div>
                      )}
                    </div>
                  </div>
                  {/* Operators sometimes need the raw error. Hidden behind a
                      disclosure so a non-technical user isn't shown JSON. */}
                  <button
                    type="button"
                    onClick={() => setShowDetails(s => !s)}
                    className="flex items-center gap-1 text-[11px] text-amber-300/70 hover:text-amber-300 transition-colors"
                  >
                    {showDetails ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                    {showDetails ? 'Hide technical details' : 'Show technical details'}
                  </button>
                  {showDetails && err && (
                    <pre className="text-[11px] text-amber-200/60 bg-tron-900/50 rounded px-2 py-1.5 font-mono overflow-x-auto whitespace-pre-wrap break-all">
                      {err}
                    </pre>
                  )}
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

        <div className="text-center space-y-1.5">
          {/* "Connected to" subtitle — finger-slipped URLs become obvious
              before the user even types a password. */}
          <p className="text-[11px] text-tron-600">
            Connected to <span className="font-mono text-tron-500">{apiOrigin}</span>
          </p>
          <p className="text-xs text-tron-600">
            Session cookie is httpOnly. Optional <span className="font-mono">X-API-Key</span> in Settings is for scripts
            and MCP only.
          </p>
        </div>
      </div>
    </div>
  )
}
