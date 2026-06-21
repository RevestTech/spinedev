import { useState, useEffect, useCallback } from 'react'
import {
  Key, KeyRound, Trash2, Sliders, Server, Shield, BookOpen,
} from 'lucide-react'
import Card, { CardHeader, CardBody } from '../components/Card'
import {
  listApiKeys,
  createApiKey,
  revokeApiKey,
  type ApiKeySummary,
  listProjects,
  type Project,
  getStandardsDefaults,
  getMergedStandards,
  getProject,
  updateProject,
  type ProjectDetail,
  getReady,
  getHealth,
  type ReadyResponse,
  type HealthResponse,
  listControlPacks,
} from '../api'

type Tab = 'general' | 'keys' | 'quality' | 'operations'

const SCOPE_OPTIONS = [
  { id: '*', label: 'Full access (*)' },
  { id: 'projects', label: 'projects' },
  { id: 'audits', label: 'audits' },
  { id: 'workflows', label: 'workflows' },
  { id: 'graph', label: 'graph' },
  { id: 'standards', label: 'standards' },
  { id: 'modes', label: 'modes (plan / build / evolve)' },
  { id: 'fixes', label: 'fixes' },
  { id: 'costs', label: 'costs' },
  { id: 'gdpr', label: 'gdpr' },
] as const

export default function Settings() {
  const [tab, setTab] = useState<Tab>('general')
  const [keys, setKeys] = useState<ApiKeySummary[]>([])
  const [keysErr, setKeysErr] = useState<string | null>(null)
  const [newLabel, setNewLabel] = useState('')
  const [createdOnce, setCreatedOnce] = useState<string | null>(null)
  const [selectedScopes, setSelectedScopes] = useState<string[]>(['*'])

  const [projects, setProjects] = useState<Project[]>([])
  const [projPick, setProjPick] = useState('')
  const [projDetail, setProjDetail] = useState<ProjectDetail | null>(null)
  const [qgText, setQgText] = useState('{}')
  const [cqgText, setCqgText] = useState('{}')
  const [gateMsg, setGateMsg] = useState<string | null>(null)
  const [defaultsJson, setDefaultsJson] = useState<string>('')
  const [mergedPreview, setMergedPreview] = useState<string>('')
  const [packs, setPacks] = useState<string[]>([])

  const [ready, setReady] = useState<ReadyResponse | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [opsErr, setOpsErr] = useState<string | null>(null)

  const refreshKeys = useCallback(async () => {
    setKeysErr(null)
    // Auth rides the admin session cookie. If the user isn't logged in, the
    // backend returns 401 and we surface that; we no longer gate on a
    // localStorage-held master key.
    try {
      const k = await listApiKeys()
      setKeys(k)
    } catch (e) {
      setKeysErr(e instanceof Error ? e.message : 'Could not load API keys.')
      setKeys([])
    }
  }, [])

  useEffect(() => {
    void refreshKeys()
  }, [refreshKeys])

  useEffect(() => {
    if (tab !== 'quality') return
    void (async () => {
      try {
        const d = await getStandardsDefaults()
        setDefaultsJson(JSON.stringify(d, null, 2))
        const p = await listControlPacks()
        setPacks(p.items.map(i => i.id))
      } catch (e) {
        setGateMsg(e instanceof Error ? e.message : 'Failed to load standards')
      }
    })()
  }, [tab])

  useEffect(() => {
    if (tab !== 'quality') return
    void (async () => {
      try {
        const pl = await listProjects(1, 100)
        setProjects(pl.items)
        setProjPick(prev => prev || pl.items[0]?.id || '')
      } catch {
        /* ignore */
      }
    })()
  }, [tab])

  useEffect(() => {
    if (tab !== 'quality' || !projPick) return
    void (async () => {
      setGateMsg(null)
      try {
        const p = await getProject(projPick)
        setProjDetail(p)
        setQgText(JSON.stringify(p.quality_gates_json ?? {}, null, 2))
        setCqgText(JSON.stringify(p.company_quality_gates_json ?? {}, null, 2))
        const m = await getMergedStandards(projPick)
        setMergedPreview(JSON.stringify(m.gates, null, 2))
      } catch (e) {
        setGateMsg(e instanceof Error ? e.message : 'Failed to load project')
      }
    })()
  }, [tab, projPick])

  useEffect(() => {
    if (tab !== 'operations') return
    void (async () => {
      setOpsErr(null)
      try {
        const [r, h] = await Promise.all([getReady(), getHealth()])
        setReady(r)
        setHealth(h)
      } catch (e) {
        setOpsErr(e instanceof Error ? e.message : 'Health check failed')
      }
    })()
  }, [tab])

  async function handleCreateScoped() {
    setCreatedOnce(null)
    setKeysErr(null)
    try {
      const scopes = selectedScopes.includes('*') ? ['*'] : [...selectedScopes]
      if (!scopes.length) {
        setKeysErr('Select at least one scope.')
        return
      }
      const row = await createApiKey({ label: newLabel || 'scoped', scopes })
      setCreatedOnce(row.api_key)
      setNewLabel('')
      await refreshKeys()
    } catch (e) {
      setKeysErr(e instanceof Error ? e.message : 'Create failed')
    }
  }

  async function handleRevoke(id: string) {
    if (!confirm('Revoke this API key?')) return
    try {
      await revokeApiKey(id)
      await refreshKeys()
    } catch (e) {
      setKeysErr(e instanceof Error ? e.message : 'Revoke failed')
    }
  }

  async function handleSaveGates() {
    setGateMsg(null)
    if (!projPick) return
    try {
      const qg = JSON.parse(qgText) as Record<string, unknown>
      const cqg = JSON.parse(cqgText) as Record<string, unknown>
      await updateProject(projPick, {
        quality_gates_json: qg,
        company_quality_gates_json: cqg,
      })
      setGateMsg('Saved project quality gate overrides.')
      const m = await getMergedStandards(projPick)
      setMergedPreview(JSON.stringify(m.gates, null, 2))
    } catch (e) {
      setGateMsg(e instanceof Error ? e.message : 'Invalid JSON or save failed')
    }
  }

  const tabs: { id: Tab; label: string; icon: typeof Key }[] = [
    { id: 'general', label: 'General', icon: Key },
    { id: 'keys', label: 'API keys', icon: KeyRound },
    { id: 'quality', label: 'Quality gates', icon: BookOpen },
    { id: 'operations', label: 'Operations', icon: Server },
  ]

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Sliders className="w-7 h-7 text-accent" />
          Settings
        </h1>
        <p className="text-tron-400 text-sm mt-1">Dashboard authentication, scoped keys, quality gates, and runtime checks</p>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-tron-700 pb-3">
        {tabs.map(t => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === t.id
                ? 'bg-accent/20 text-accent-light border border-accent/40'
                : 'text-tron-400 hover:bg-tron-800 hover:text-white border border-transparent'
            }`}
          >
            <t.icon className="w-4 h-4" />
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'general' && (
        <>
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Key className="w-4 h-4 text-tron-400" />
                <span className="text-sm font-medium text-white">Session auth</span>
              </div>
            </CardHeader>
            <CardBody className="space-y-3 text-sm text-tron-400">
              <p>
                You signed in on the <strong className="text-tron-300">/login</strong> page. The browser now holds an
                httpOnly session cookie — JavaScript in this page cannot read it, and it is sent automatically on
                every request to <code className="text-tron-300">/api</code> and <code className="text-tron-300">/ws</code>.
              </p>
              <p>
                Need to call the API from a script or CLI? Mint a scoped key on the{' '}
                <strong className="text-tron-300">API keys</strong> tab and pass it as an{' '}
                <code className="text-tron-300">X-API-Key</code> header from that tool. The SPA itself does not store
                API keys in browser storage — that would make them reachable by any injected script.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-white">Endpoints</span>
            </CardHeader>
            <CardBody className="space-y-2 text-sm text-tron-400">
              <p>
                This SPA is usually served by <strong className="text-tron-300">nginx</strong> so{' '}
                <code className="text-accent-light">/api</code> and <code className="text-accent-light">/ws</code>{' '}
                match the same host you opened in the browser (recommended:{' '}
                <span className="text-tron-300 font-mono">http://localhost:13080</span>).
              </p>
              <p>
                Direct API (compose): <span className="font-mono text-tron-300">http://127.0.0.1:13000</span> — use
                only when bypassing nginx; WebSockets from the SPA expect the nginx host.
              </p>
            </CardBody>
          </Card>
        </>
      )}

      {tab === 'keys' && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4 text-tron-400" />
              <span className="text-sm font-medium text-white">Scoped API keys</span>
            </div>
          </CardHeader>
          <CardBody className="space-y-4">
            <p className="text-sm text-tron-400">
              Requires an authenticated admin session (the httpOnly cookie from <strong className="text-tron-300">/login</strong>).
              Scoped keys are shown in plaintext exactly once — copy them into your CLI/CI secret store right after creation.
            </p>
            {keysErr && <p className="text-sm text-amber-400/90">{keysErr}</p>}
            {createdOnce && (
              <div className="rounded-lg bg-tron-700/80 border border-accent/40 p-3 text-sm">
                <div className="text-tron-300 mb-1">New key (copy now):</div>
                <code className="text-accent-light break-all select-all">{createdOnce}</code>
              </div>
            )}
            <div className="space-y-2">
              <div className="text-xs text-tron-500 uppercase tracking-wide">Scopes for new key</div>
              <p className="text-xs text-tron-600">
                Graph endpoints require both <code className="text-tron-500">graph</code> and{' '}
                <code className="text-tron-500">projects</code> scopes (or <code className="text-tron-500">*</code>).
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {SCOPE_OPTIONS.map(opt => (
                  <label
                    key={opt.id}
                    className="flex items-center gap-2 text-sm text-tron-300 cursor-pointer hover:text-white"
                  >
                    <input
                      type="checkbox"
                      checked={selectedScopes.includes(opt.id)}
                      onChange={() => {
                        if (opt.id === '*') {
                          setSelectedScopes(['*'])
                          return
                        }
                        setSelectedScopes(prev => {
                          const without = prev.filter(s => s !== '*')
                          if (without.includes(opt.id)) return without.filter(s => s !== opt.id)
                          return [...without, opt.id]
                        })
                      }}
                      className="rounded border-tron-600"
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
            </div>
            <div className="flex gap-2 flex-wrap">
              <input
                type="text"
                value={newLabel}
                onChange={e => setNewLabel(e.target.value)}
                placeholder="Label (e.g. CI bot)"
                className="flex-1 min-w-[160px] bg-tron-700 border border-tron-600 rounded-lg px-3 py-2 text-sm text-white placeholder-tron-500 focus:outline-none focus:border-accent"
              />
              <button
                type="button"
                onClick={() => void handleCreateScoped()}
                className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm font-medium"
              >
                Create key
              </button>
            </div>
            <ul className="divide-y divide-tron-700 border border-tron-700 rounded-lg overflow-hidden">
              {keys.map(k => (
                <li key={k.id} className="flex items-center justify-between px-3 py-2 text-sm bg-tron-800/50">
                  <div>
                    <div className="text-white font-medium">{k.label}</div>
                    <div className="text-tron-500 text-xs font-mono">
                      {k.id.slice(0, 8)}… · {k.scopes.join(', ')}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleRevoke(k.id)}
                    className="p-2 text-tron-400 hover:text-red-400"
                    title="Revoke"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </li>
              ))}
              {keys.length === 0 && !keysErr && (
                <li className="px-3 py-6 text-center text-tron-500 text-sm">No scoped keys yet.</li>
              )}
            </ul>
          </CardBody>
        </Card>
      )}

      {tab === 'quality' && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-white">Built-in defaults (read-only)</span>
            </CardHeader>
            <CardBody>
              <pre className="text-xs text-tron-300 bg-tron-950 p-3 rounded-lg overflow-x-auto max-h-48 border border-tron-700">
                {defaultsJson || 'Loading…'}
              </pre>
              <p className="text-xs text-tron-500 mt-2">
                From <code className="text-tron-400">GET /api/standards/defaults</code>. Deploy-time limits (LLM budget,
                sandbox URL, etc.) stay in environment / compose — not editable here.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-white">Reference control packs</span>
            </CardHeader>
            <CardBody className="text-sm text-tron-400">
              {packs.length > 0 ? (
                <p>
                  Available pack ids:{' '}
                  <span className="text-tron-200 font-mono text-xs">{packs.join(', ')}</span>. Assign packs on the{' '}
                  <strong className="text-tron-300">project</strong> detail page (
                  <code className="text-tron-500">compliance_control_pack_ids</code>).
                </p>
              ) : (
                <p>Load packs from the API (requires standards scope).</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-white">Project overrides</span>
            </CardHeader>
            <CardBody className="space-y-4">
              <p className="text-sm text-tron-400">
                Edit <code className="text-tron-500">quality_gates_json</code> and{' '}
                <code className="text-tron-500">company_quality_gates_json</code> (must be valid JSON objects). Saved
                via <code className="text-tron-500">PUT /api/projects/:id</code>.
              </p>
              {gateMsg && (
                <p className={`text-sm ${gateMsg.startsWith('Saved') ? 'text-green-400' : 'text-amber-400'}`}>
                  {gateMsg}
                </p>
              )}
              <div className="flex flex-wrap gap-3 items-center">
                <label className="text-xs text-tron-500">Project</label>
                <select
                  value={projPick}
                  onChange={e => setProjPick(e.target.value)}
                  className="bg-tron-700 border border-tron-600 rounded-lg px-3 py-2 text-sm text-white min-w-[200px]"
                >
                  {projects.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
                {projDetail && (
                  <span className="text-xs text-tron-500 truncate max-w-[240px]">{projDetail.repo_url || 'No repo URL'}</span>
                )}
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-tron-500 mb-1">quality_gates_json</div>
                  <textarea
                    value={qgText}
                    onChange={e => setQgText(e.target.value)}
                    rows={12}
                    className="w-full font-mono text-xs bg-tron-950 border border-tron-700 rounded-lg p-3 text-tron-200 focus:outline-none focus:border-accent"
                  />
                </div>
                <div>
                  <div className="text-xs text-tron-500 mb-1">company_quality_gates_json</div>
                  <textarea
                    value={cqgText}
                    onChange={e => setCqgText(e.target.value)}
                    rows={12}
                    className="w-full font-mono text-xs bg-tron-950 border border-tron-700 rounded-lg p-3 text-tron-200 focus:outline-none focus:border-accent"
                  />
                </div>
              </div>
              <button
                type="button"
                onClick={() => void handleSaveGates()}
                className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm font-medium"
              >
                Save project gates
              </button>
              <div>
                <div className="text-xs text-tron-500 mb-1">Merged preview (default + company + project)</div>
                <pre className="text-xs text-tron-400 bg-tron-950 p-3 rounded-lg overflow-x-auto max-h-56 border border-tron-700">
                  {mergedPreview || '{}'}
                </pre>
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {tab === 'operations' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-white">Readiness</span>
            </CardHeader>
            <CardBody className="space-y-2 text-sm">
              {opsErr && <p className="text-amber-400">{opsErr}</p>}
              {ready ? (
                <>
                  <div className="text-tron-400">
                    Status: <span className="text-white font-medium">{ready.status}</span>
                  </div>
                  <ul className="text-xs text-tron-500 space-y-1 font-mono">
                    {Object.entries(ready.checks).map(([k, v]) => (
                      <li key={k}>
                        {k}: <span className="text-tron-300">{v}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                !opsErr && <p className="text-tron-500">Loading…</p>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-white">API liveness</span>
            </CardHeader>
            <CardBody className="space-y-2 text-sm text-tron-400">
              {health ? (
                <>
                  <div>
                    Service: <span className="text-white">{health.service}</span>
                  </div>
                  <div>
                    State: <span className="text-white">{health.status}</span>
                  </div>
                  <div>Uptime: {Math.round(health.uptime_seconds)}s</div>
                </>
              ) : (
                !opsErr && <p className="text-tron-500">Loading…</p>
              )}
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  )
}
