import { useState, useEffect, useCallback } from 'react'
import {
  Search, Globe, Star, ChevronDown,
  X, AlertCircle, RefreshCw, Check, Plus, Trash2, Pin,
} from 'lucide-react'
import * as api from '../api'

interface Props {
  onSelect: (repo: api.GithubRepo) => void;
  onClose: () => void;
}

// Persist the last-selected org login across sessions so the dropdown
// pre-selects what the user used last time. Cheap UX win that costs
// nothing — only the login string is stored, no PII.
const LAST_ORG_KEY = 'tron.github.lastOrg'

function readLastOrg(): string | null {
  try {
    return window.localStorage.getItem(LAST_ORG_KEY)
  } catch {
    return null
  }
}

function writeLastOrg(login: string | null) {
  try {
    if (login) window.localStorage.setItem(LAST_ORG_KEY, login)
    else window.localStorage.removeItem(LAST_ORG_KEY)
  } catch {
    // localStorage may be unavailable in some embedded contexts; ignore.
  }
}

export default function GithubRepoBrowser({ onSelect, onClose }: Props) {
  const [repos, setRepos] = useState<api.GithubRepo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  // Saved-org state
  const [savedOrgs, setSavedOrgs] = useState<api.SavedGithubOrg[]>([])
  const [activeOrg, setActiveOrg] = useState<string | null>(readLastOrg())
  const [orgPickerOpen, setOrgPickerOpen] = useState(false)
  const [addingOrg, setAddingOrg] = useState(false)
  const [newOrgLogin, setNewOrgLogin] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  // Initial load: pull saved orgs + fetch repos for last-selected (or "my repos")
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const list = await api.listSavedGithubOrgs()
        if (cancelled) return
        setSavedOrgs(list)
        // If we remembered a login but it's been removed since, clear it.
        if (activeOrg && !list.some(o => o.login === activeOrg)) {
          setActiveOrg(null)
          writeLastOrg(null)
          await fetchRepos(null)
        } else {
          await fetchRepos(activeOrg)
        }
      } catch (err: unknown) {
        // Loading saved orgs failed — fall back to plain repo fetch so
        // the dialog isn't dead in the water.
        if (!cancelled) await fetchRepos(activeOrg)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchRepos = useCallback(async (org: string | null) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listGithubRepos(org ?? undefined)
      setRepos(data)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to connect to GitHub.'
      setError(msg || 'Failed to connect to GitHub. Check your token in settings.')
    } finally {
      setLoading(false)
    }
  }, [])

  function selectOrg(login: string | null) {
    setActiveOrg(login)
    writeLastOrg(login)
    setOrgPickerOpen(false)
    fetchRepos(login)
  }

  async function handleAddOrg(e: React.FormEvent) {
    e.preventDefault()
    setAddError(null)
    const login = newOrgLogin.trim()
    if (!login) return
    try {
      const row = await api.addSavedGithubOrg({ login })
      // Idempotent: if it already existed the backend returns the existing row.
      setSavedOrgs(prev => {
        const without = prev.filter(o => o.login !== row.login)
        return [row, ...without]
      })
      setNewOrgLogin('')
      setAddingOrg(false)
      selectOrg(row.login)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to add org.'
      // Trim the leading "<status> <statusText>: " prefix from request()
      const cleaned = msg.replace(/^\d{3}\s[^:]+:\s*/, '')
      setAddError(cleaned)
    }
  }

  async function handleRemoveOrg(id: string, login: string) {
    try {
      await api.deleteSavedGithubOrg(id)
      setSavedOrgs(prev => prev.filter(o => o.id !== id))
      if (activeOrg === login) {
        selectOrg(null)
      }
    } catch (err: unknown) {
      // Non-fatal — show error inline near the picker
      const msg = err instanceof Error ? err.message : 'Failed to remove.'
      setAddError(msg)
    }
  }

  const filtered = repos.filter(r =>
    r.full_name.toLowerCase().includes(query.toLowerCase()) ||
    (r.description || '').toLowerCase().includes(query.toLowerCase())
  )

  const activeOrgRow = activeOrg
    ? savedOrgs.find(o => o.login === activeOrg)
    : null
  const activeLabel = activeOrgRow
    ? (activeOrgRow.display_name || activeOrgRow.login)
    : (activeOrg || 'My repos (PAT default)')

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-tron-950/90 backdrop-blur-md" onClick={onClose} />

      <div className="relative w-full max-w-2xl bg-tron-800 border border-tron-700 rounded-[2.5rem] shadow-2xl flex flex-col max-h-[80vh] overflow-hidden animate-in zoom-in-95 duration-300">

        {/* Header */}
        <div className="p-8 border-b border-tron-700 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-white/10 rounded-2xl text-accent-light">
              <Globe className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-black text-white tracking-tight">Organization Repositories</h2>
              <p className="text-xs text-tron-400 font-bold uppercase tracking-widest mt-1">Connect your code</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-tron-500 hover:text-white transition-colors">
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Org switcher + search */}
        <div className="p-6 bg-tron-900/40 border-b border-tron-700 space-y-4">
          {/* Org picker — replaces the old free-text "GitHub org or username" field. */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setOrgPickerOpen(o => !o)}
              className="w-full flex items-center justify-between gap-3 bg-tron-900 border border-tron-700 hover:border-accent/40 rounded-xl py-2.5 px-4 text-left transition-colors"
            >
              <span className="flex items-center gap-2 min-w-0">
                <Globe className="w-4 h-4 text-tron-500 shrink-0" />
                <span className="text-sm font-bold text-white truncate">
                  {activeLabel}
                </span>
                {activeOrgRow && (
                  <span className="text-[10px] font-black text-tron-500 uppercase tracking-widest">
                    {activeOrgRow.kind}
                  </span>
                )}
              </span>
              <ChevronDown className={`w-4 h-4 text-tron-500 transition-transform ${orgPickerOpen ? 'rotate-180' : ''}`} />
            </button>

            {orgPickerOpen && (
              <div className="absolute z-10 mt-2 w-full bg-tron-900 border border-tron-700 rounded-xl shadow-xl overflow-hidden">
                <button
                  type="button"
                  onClick={() => selectOrg(null)}
                  className={`w-full text-left px-4 py-2.5 text-sm font-medium transition-colors ${activeOrg === null ? 'bg-accent/10 text-accent-light' : 'text-tron-300 hover:bg-tron-800'}`}
                >
                  My repos (PAT default)
                </button>

                {savedOrgs.length > 0 && (
                  <div className="border-t border-tron-700 max-h-56 overflow-y-auto">
                    {savedOrgs.map(o => (
                      <div
                        key={o.id}
                        className={`flex items-center justify-between px-4 py-2.5 transition-colors ${activeOrg === o.login ? 'bg-accent/10' : 'hover:bg-tron-800'}`}
                      >
                        <button
                          type="button"
                          onClick={() => selectOrg(o.login)}
                          className="flex items-center gap-2 flex-1 min-w-0 text-left"
                        >
                          {o.pinned && <Pin className="w-3 h-3 text-accent-light shrink-0" />}
                          <span className={`text-sm font-medium truncate ${activeOrg === o.login ? 'text-accent-light' : 'text-tron-200'}`}>
                            {o.display_name || o.login}
                          </span>
                          <span className="text-[10px] font-black text-tron-500 uppercase tracking-widest shrink-0">
                            {o.kind}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => handleRemoveOrg(o.id, o.login)}
                          className="p-1.5 text-tron-600 hover:text-red-400 transition-colors shrink-0"
                          aria-label={`Remove ${o.login}`}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="border-t border-tron-700">
                  {addingOrg ? (
                    <form onSubmit={handleAddOrg} className="p-3 space-y-2">
                      <div className="flex gap-2">
                        <input
                          type="text"
                          autoFocus
                          placeholder="github-org-or-username"
                          value={newOrgLogin}
                          onChange={e => setNewOrgLogin(e.target.value)}
                          className="flex-1 bg-tron-950 border border-tron-700 rounded-lg py-1.5 px-3 text-sm text-white focus:outline-none focus:border-accent"
                        />
                        <button
                          type="submit"
                          className="px-3 py-1.5 bg-accent hover:bg-accent-dark text-white rounded-lg text-xs font-black uppercase tracking-widest transition-colors"
                        >
                          Add
                        </button>
                        <button
                          type="button"
                          onClick={() => { setAddingOrg(false); setNewOrgLogin(''); setAddError(null) }}
                          className="px-3 py-1.5 text-tron-400 hover:text-white text-xs font-black uppercase tracking-widest"
                        >
                          Cancel
                        </button>
                      </div>
                      {addError && (
                        <p className="text-[11px] text-red-300 leading-snug">{addError}</p>
                      )}
                      <p className="text-[11px] text-tron-500 leading-snug">
                        Tron will verify the login resolves on GitHub before saving.
                      </p>
                    </form>
                  ) : (
                    <button
                      type="button"
                      onClick={() => { setAddingOrg(true); setAddError(null) }}
                      className="w-full flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-accent-light hover:bg-tron-800 transition-colors"
                    >
                      <Plus className="w-4 h-4" />
                      Add another org
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Repo search */}
          <div className="relative group">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-tron-500 group-focus-within:text-accent transition-colors" />
            <input
              type="text"
              placeholder="Search available repositories..."
              className="w-full bg-tron-950 border-2 border-tron-700 rounded-2xl py-3 pl-12 pr-4 text-sm font-bold text-white focus:outline-none focus:border-accent transition-all placeholder:text-tron-700"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Repo List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2 scrollbar-hide">
          {loading ? (
             <div className="flex flex-col items-center justify-center py-20 text-tron-500 gap-4">
                <RefreshCw className="w-8 h-8 animate-spin text-accent" />
                <p className="text-sm font-black uppercase tracking-widest">Querying GitHub API...</p>
             </div>
          ) : error ? (
            <div className="p-8 text-center space-y-4">
               <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl inline-block">
                  <AlertCircle className="w-8 h-8 text-red-400 mx-auto" />
               </div>
               <p className="text-sm text-red-200 font-medium max-w-xs mx-auto leading-relaxed">{error}</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-16 px-6 text-center text-tron-500 space-y-3 max-w-md mx-auto">
               <p className="text-sm font-bold italic">No repositories found.</p>
               {repos.length === 0 && (
                 <p className="text-xs text-tron-600 leading-relaxed">
                   {activeOrg
                     ? `Tron's PAT can't see any repos under ${activeOrg}. SSO-enabled orgs need the PAT authorized — see Settings.`
                     : 'Add an org from the dropdown above, or paste an HTTPS clone URL into the project form manually.'}
                 </p>
               )}
               {repos.length > 0 && query.trim() !== '' && (
                 <p className="text-xs text-tron-600">Try clearing the search box — nothing matches &quot;{query}&quot;.</p>
               )}
            </div>
          ) : (
            filtered.map(repo => (
              <button
                key={repo.html_url}
                onClick={() => onSelect(repo)}
                className="w-full text-left p-5 bg-tron-800/40 border border-tron-700/50 rounded-[1.5rem] hover:bg-tron-700/50 hover:border-accent/40 transition-all group flex items-center justify-between"
              >
                <div className="space-y-1 pr-4">
                  <div className="text-white font-black text-sm group-hover:text-accent-light transition-colors">{repo.full_name}</div>
                  {repo.description && <div className="text-[11px] text-tron-400 line-clamp-1">{repo.description}</div>}
                  <div className="flex items-center gap-4 pt-1">
                     <span className="flex items-center gap-1.5 text-[10px] font-black text-tron-500 uppercase tracking-tighter">
                        <div className="w-1.5 h-1.5 rounded-full bg-accent-light" /> {repo.language || 'Mixed'}
                     </span>
                     <span className="flex items-center gap-1.5 text-[10px] font-black text-tron-500 uppercase tracking-tighter">
                        <Star className="w-3 h-3" /> {repo.stargazers_count}
                     </span>
                  </div>
                </div>
                <div className="p-2.5 bg-tron-900 rounded-xl group-hover:bg-accent group-hover:text-white transition-all text-tron-600">
                   <Check className="w-5 h-5" />
                </div>
              </button>
            ))
          )}
        </div>

        <div className="p-6 border-t border-tron-700 bg-tron-900/40 flex justify-between items-center">
           <span className="text-[10px] font-black text-tron-500 uppercase tracking-widest italic">Tron Enterprise Github Connector</span>
           <button onClick={onClose} className="text-xs font-black text-tron-400 hover:text-white transition-colors uppercase tracking-widest">Close Browser</button>
        </div>
      </div>
    </div>
  )
}
