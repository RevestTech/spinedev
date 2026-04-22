import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  FolderGit2, Plus, GitBranch, Trash2, Play, ChevronRight,
  Bug, CheckCircle2, Clock, RefreshCw, Globe
} from 'lucide-react'
import Card, { CardHeader, CardBody } from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import GithubRepoBrowser from '../components/GithubRepoBrowser'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

export default function Projects() {
  const { data, refetch } = usePolling(() => api.listProjects(1, 100), 10000, [])
  const { data: audits } = usePolling(() => api.listAudits({ page_size: 200 }), 8000, [])
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [showGithub, setShowGithub] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', repo_url: '', default_branch: 'main' })
  const [creating, setCreating] = useState(false)
  const [scanning, setScanning] = useState<string | null>(null)

  const projects = data?.items ?? []
  const auditItems = audits?.items ?? []

  // Build per-project audit stats
  function getProjectStats(projectId: string) {
    const projectAudits = auditItems.filter(a => a.project_id === projectId)
    const completed = projectAudits.filter(a => a.status === 'completed')
    const running = projectAudits.some(a => a.status === 'running' || a.status === 'queued')
    const latest = projectAudits[0] ?? null
    const totalFindings = completed.reduce((s, a) => s + a.findings_total, 0)
    const totalCritical = completed.reduce((s, a) => s + a.findings_critical, 0)
    return { auditCount: projectAudits.length, completed: completed.length, running, latest, totalFindings, totalCritical }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      await api.createProject({
        name: form.name,
        description: form.description || undefined,
        repo_url: form.repo_url || undefined,
        default_branch: form.default_branch || 'main',
      })
      setShowCreate(false)
      setForm({ name: '', description: '', repo_url: '', default_branch: 'main' })
      refetch()
    } finally {
      setCreating(false)
    }
  }

  async function handleScan(projectId: string, branch: string) {
    setScanning(projectId)
    try {
      await api.createAudit({ project_id: projectId, branch, trigger_type: 'manual' })
      refetch()
    } finally {
      setScanning(null)
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this project?')) return
    await api.deleteProject(id)
    refetch()
  }

  function handleGithubSelect(repo: api.GithubRepo) {
    setForm({
      name: repo.name,
      description: repo.description || '',
      repo_url: repo.html_url,
      default_branch: 'main'
    })
    setShowGithub(false)
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Projects</h1>
          <p className="text-tron-400 text-sm mt-1">{projects.length} project{projects.length !== 1 ? 's' : ''} active</p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent-dark text-white rounded-xl text-sm font-bold transition-all shadow-lg shadow-accent/20"
        >
          <Plus className="w-4 h-4" /> New Project
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card className="animate-in slide-in-from-top-4 duration-300">
          <CardBody>
            <div className="flex justify-between items-center mb-6">
               <h3 className="text-white font-bold tracking-tight">Register New Project</h3>
               <button 
                onClick={() => setShowGithub(true)}
                className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 text-white rounded-xl text-xs font-black uppercase tracking-widest border border-white/10 transition-all"
               >
                 <Globe className="w-3.5 h-3.5" /> Connect Organization Repo
               </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-[10px] font-black text-tron-500 uppercase tracking-widest mb-2">Project Name *</label>
                  <input
                    required
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full bg-tron-950 border-2 border-tron-700 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-accent transition-all"
                    placeholder="e.g. Finance API"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-black text-tron-500 uppercase tracking-widest mb-2">Repository URL</label>
                  <input
                    value={form.repo_url}
                    onChange={e => setForm(f => ({ ...f, repo_url: e.target.value }))}
                    className="w-full bg-tron-950 border-2 border-tron-700 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-accent transition-all"
                    placeholder="https://github.com/org/repo.git"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-black text-tron-500 uppercase tracking-widest mb-2">Default Branch</label>
                  <input
                    value={form.default_branch}
                    onChange={e => setForm(f => ({ ...f, default_branch: e.target.value }))}
                    className="w-full bg-tron-950 border-2 border-tron-700 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-accent transition-all"
                    placeholder="main"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-black text-tron-500 uppercase tracking-widest mb-2">Description</label>
                  <input
                    value={form.description}
                    onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    className="w-full bg-tron-950 border-2 border-tron-700 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-accent transition-all"
                    placeholder="Optional project context"
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={creating}
                  className="px-6 py-3 bg-accent hover:bg-accent-dark text-white rounded-xl text-xs font-black uppercase tracking-widest transition-all disabled:opacity-50"
                >
                  {creating ? 'Creating...' : 'Register Project'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="px-6 py-3 bg-tron-800 hover:bg-tron-700 text-tron-300 rounded-xl text-xs font-black uppercase tracking-widest transition-all"
                >
                  Cancel
                </button>
              </div>
            </form>
          </CardBody>
        </Card>
      )}

      {/* GitHub Browser Modal */}
      {showGithub && (
        <GithubRepoBrowser 
          onSelect={handleGithubSelect}
          onClose={() => setShowGithub(false)}
        />
      )}

      {/* Projects list */}
      <div className="grid gap-4">
        {projects.map(p => {
          const stats = getProjectStats(p.id)
          return (
            <Card key={p.id} className="group hover:border-tron-500 transition-colors cursor-pointer" onClick={() => navigate(`/projects/${p.id}`)}>
              <CardBody className="flex items-center justify-between">
                <div className="flex items-center gap-4 min-w-0">
                  <div className="w-10 h-10 rounded-lg bg-tron-700 flex items-center justify-center shrink-0">
                    <FolderGit2 className="w-5 h-5 text-accent-light" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-white font-medium text-sm group-hover:text-accent-light transition-colors">{p.name}</div>
                    {p.description && <div className="text-tron-400 text-xs mt-0.5 truncate">{p.description}</div>}
                    <div className="flex items-center gap-3 mt-1">
                      <span className="flex items-center gap-1 text-tron-500 text-xs">
                        <GitBranch className="w-3 h-3" /> {p.default_branch}
                      </span>
                      {stats.auditCount > 0 && (
                        <>
                          <span className="flex items-center gap-1 text-tron-500 text-xs">
                            <Clock className="w-3 h-3" /> {stats.auditCount} scan{stats.auditCount !== 1 ? 's' : ''}
                          </span>
                          {stats.totalFindings === 0 && stats.completed > 0 ? (
                            <span className="flex items-center gap-1 text-green-400 text-xs font-medium">
                              <CheckCircle2 className="w-3 h-3" /> Clean
                            </span>
                          ) : stats.totalCritical > 0 ? (
                            <span className="flex items-center gap-1 text-red-400 text-xs font-medium">
                              <Bug className="w-3 h-3" /> {stats.totalCritical} critical
                            </span>
                          ) : stats.totalFindings > 0 ? (
                            <span className="flex items-center gap-1 text-orange-400 text-xs font-medium">
                              <Bug className="w-3 h-3" /> {stats.totalFindings} finding{stats.totalFindings !== 1 ? 's' : ''}
                            </span>
                          ) : null}
                          {stats.running && (
                            <span className="flex items-center gap-1 text-accent-light text-xs">
                              <RefreshCw className="w-3 h-3 animate-spin" /> Running
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <StatusBadge status={p.status} />
                  <button
                    onClick={(e) => { e.stopPropagation(); handleScan(p.id, p.default_branch); }}
                    disabled={scanning === p.id || stats.running}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/15 hover:bg-accent/25 text-accent-light rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
                  >
                    <Play className="w-3 h-3" /> {scanning === p.id ? 'Starting...' : 'Scan'}
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(p.id); }}
                    className="p-1.5 text-tron-500 hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  <ChevronRight className="w-4 h-4 text-tron-600 group-hover:text-tron-400 transition-colors" />
                </div>
              </CardBody>
            </Card>
          )
        })}
        {projects.length === 0 && (
          <Card>
            <CardBody className="text-center py-12 text-tron-500">
              No projects yet. Click "New Project" to get started.
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  )
}
