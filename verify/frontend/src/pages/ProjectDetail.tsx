import { useState, useMemo, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Play, GitBranch, Bug, AlertTriangle,
  CheckCircle2, XCircle, FileCode, ChevronRight, BarChart3,
  Shield, Zap, RefreshCw, ClipboardList, TrendingUp,
  Share2, Info, Globe, Settings
} from 'lucide-react'
import GithubRepoBrowser from '../components/GithubRepoBrowser'

import ForceGraph2D from 'react-force-graph-2d'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  AreaChart, Area, CartesianGrid,
} from 'recharts'
import Card, { CardHeader, CardBody } from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

const SEV_COLORS: Record<string, string> = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#eab308',
  low: '#22c55e',
}

interface PlanArtifact {
  architecture_summary?: string
  requirements_bullets?: string[]
  test_plan_outline?: string[]
  risks?: string[]
  compiled_goals?: string
  compiled_constraints?: string
}

interface BuildResult {
  task?: string
  quality_gates_passed?: boolean
  quality_gate_criteria?: Array<{
    gate: string
    passed: boolean
    actual: number | string
    threshold: number | string
    reason?: string
  }>
  validation?: {
    ok: boolean
    command: string
    exit_code: number
    log_tail?: string
  }
  findings_count?: number
  duration_seconds?: number
}

interface EvolveArtifact {
  directive?: string
  findings_count?: number
  duration_seconds?: number
  errors?: string
  findings?: any[]
}

function LiveAuditStatus({ auditId }: { auditId: string }) {
  const [events, setEvents] = useState<any[]>([])
  
  useEffect(() => {
    const ws = api.connectAuditWs(auditId, (msg: any) => {
      setEvents(prev => [...prev.slice(-10), msg])
    })
    return () => ws.close()
  }, [auditId])

  if (events.length === 0) return null

  return (
    <Card className="border-accent/30 bg-accent/5">
      <CardHeader className="flex items-center justify-between py-2 px-4">
        <div className="flex items-center gap-2">
          <RefreshCw className="w-3.5 h-3.5 text-accent-light animate-spin" />
          <span className="text-[10px] font-black text-white uppercase tracking-widest">Live Audit Feed</span>
        </div>
        <span className="text-[9px] font-mono text-tron-500 uppercase">{auditId.slice(0, 8)}</span>
      </CardHeader>
      <CardBody className="p-4 pt-0">
        <div className="space-y-1.5 font-mono text-[10px]">
          {events.slice().reverse().map((ev, i) => (
            <div key={i} className="flex gap-3 text-tron-400">
               <span className="text-tron-600 shrink-0">[{new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}]</span>
               <span className="text-accent-light shrink-0 uppercase tracking-tighter">{ev.event || 'LOG'}</span>
               <span className="text-tron-200 truncate">
                 {ev.data?.message || ev.data?.agent || JSON.stringify(ev.data).slice(0, 80)}
               </span>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

function DependencyGraph({projectId }: { projectId: string }) {
  const [graphData, setGraphData] = useState<api.ProjectGraphResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hoverNode, setHoverNode] = useState<api.CodeFileNode | null>(null)

  useEffect(() => {
    api.getProjectGraph(projectId, 300)
      .then(setGraphData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [projectId])

  const formattedData = useMemo(() => {
    if (!graphData) return { nodes: [], links: [] }
    return {
      nodes: graphData.nodes.map(n => ({
        ...n,
        id: n.file_path,
        name: n.file_path.split('/').pop(),
        val: Math.sqrt(n.lines_of_code || 100) / 10 + 2
      })),
      links: graphData.edges.map(e => ({
        source: e.source_path,
        target: e.target_path,
        type: e.dependency_type
      }))
    }
  }, [graphData])

  if (loading) return <div className="h-[600px] flex items-center justify-center text-tron-500">Loading graph data...</div>
  if (error) return <div className="h-[600px] flex items-center justify-center text-red-500">Error: {error}</div>
  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="h-[600px] flex flex-col items-center justify-center text-tron-500 text-center px-4">
        <Share2 className="w-12 h-12 mb-4 opacity-20" />
        <h3 className="text-lg font-bold text-tron-300">No Graph Data</h3>
        <p className="max-w-md mt-2">
          Run an audit scan to populate the dependency graph. The graph maps file imports and internal architecture.
        </p>
      </div>
    )
  }

  return (
    <div className="relative group">
      <div className="absolute top-4 left-4 z-10 space-y-2">
        <div className="bg-tron-900/80 backdrop-blur border border-tron-700 p-3 rounded-lg shadow-xl">
          <div className="text-xs font-bold text-tron-400 uppercase tracking-wider mb-2 flex items-center gap-2">
             <Info className="w-3 h-3" /> Graph Insights
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
             <div className="text-[10px] text-tron-500">Files</div>
             <div className="text-[10px] text-tron-200 font-mono text-right">{graphData.total_nodes}</div>
             <div className="text-[10px] text-tron-500">Dependencies</div>
             <div className="text-[10px] text-tron-200 font-mono text-right">{graphData.total_edges}</div>
          </div>
        </div>

        {hoverNode && (
          <div className="bg-tron-900/90 backdrop-blur border border-accent/30 p-3 rounded-lg shadow-xl animate-in fade-in slide-in-from-left-2 duration-200">
            <div className="text-[10px] font-bold text-accent uppercase mb-1">Selected File</div>
            <div className="text-xs font-bold text-white mb-1 truncate max-w-[240px]">{hoverNode.file_path}</div>
            <div className="flex gap-3 mt-2">
               <div>
                 <div className="text-[9px] text-tron-500 uppercase">LOC</div>
                 <div className="text-xs text-tron-200">{hoverNode.lines_of_code || '—'}</div>
               </div>
               <div>
                 <div className="text-[9px] text-tron-500 uppercase">Imports</div>
                 <div className="text-xs text-tron-200">{hoverNode.dependency_count}</div>
               </div>
               <div>
                 <div className="text-[9px] text-tron-500 uppercase">Dependents</div>
                 <div className="text-xs text-tron-200">{hoverNode.dependent_count}</div>
               </div>
            </div>
          </div>
        )}
      </div>

      <div className="bg-tron-950 rounded-xl overflow-hidden border border-tron-800 h-[600px]">
        <ForceGraph2D
          graphData={formattedData}
          nodeLabel={(n: any) => n.file_path}
          nodeColor={(n: any) => {
             if (n.language === 'python') return '#3776ab'
             if (n.language === 'typescript' || n.language === 'ts') return '#3178c6'
             if (n.language === 'javascript' || n.language === 'js') return '#f7df1e'
             return '#94a3b8'
          }}
          nodeRelSize={6}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkColor={() => '#334155'}
          onNodeHover={(n: any) => setHoverNode(n)}
          backgroundColor="#020617"
          width={window.innerWidth > 1200 ? 1100 : window.innerWidth - 100}
          height={600}
        />
      </div>

      <div className="absolute bottom-4 right-4 text-[10px] text-tron-600 flex items-center gap-3 bg-tron-900/50 px-2 py-1 rounded">
         <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#3776ab]"></span> Python</span>
         <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#3178c6]"></span> TS</span>
         <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#f7df1e]"></span> JS</span>
      </div>
    </div>
  )
}

function PlanArtifactView({ artifact }: { artifact: any }) {
  const plan = artifact as PlanArtifact
  return (
    <div className="space-y-4">
      {plan.architecture_summary && (
        <div>
          <h4 className="text-xs font-semibold text-tron-400 uppercase tracking-wider mb-1">Architecture</h4>
          <p className="text-sm text-tron-200 leading-relaxed">{plan.architecture_summary}</p>
        </div>
      )}

      {plan.requirements_bullets && plan.requirements_bullets.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-tron-400 uppercase tracking-wider mb-1">Requirements</h4>
          <ul className="space-y-1">
            {plan.requirements_bullets.map((g, i) => (
              <li key={i} className="text-sm text-tron-300 flex gap-2">
                <span className="text-tron-500">•</span>
                <span>{g}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.test_plan_outline && plan.test_plan_outline.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-tron-400 uppercase tracking-wider mb-1">Test Plan</h4>
          <ul className="space-y-1">
            {plan.test_plan_outline.map((t, i) => (
              <li key={i} className="text-sm text-tron-300 flex gap-2">
                <span className="text-tron-500">•</span>
                <span>{t}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.risks && plan.risks.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-tron-400 uppercase tracking-wider mb-1">Risks</h4>
          <ul className="space-y-1">
            {plan.risks.map((r, i) => (
              <li key={i} className="text-sm text-tron-300 flex gap-2">
                <span className="text-orange-500/70">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(plan.compiled_goals || plan.compiled_constraints) && (
        <div className="pt-2 border-t border-tron-800">
          <details className="group">
            <summary className="text-[10px] font-bold text-tron-500 uppercase cursor-pointer hover:text-tron-400 transition-colors list-none flex items-center gap-1">
              <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
              Source Goals & Constraints
            </summary>
            <div className="mt-2 space-y-2">
              {plan.compiled_goals && (
                <div>
                  <div className="text-[9px] text-tron-600 uppercase font-bold">Goals</div>
                  <p className="text-[11px] text-tron-400 line-clamp-3 hover:line-clamp-none whitespace-pre-wrap">{plan.compiled_goals}</p>
                </div>
              )}
              {plan.compiled_constraints && (
                <div>
                  <div className="text-[9px] text-tron-600 uppercase font-bold">Constraints</div>
                  <p className="text-[11px] text-tron-400 line-clamp-3 hover:line-clamp-none whitespace-pre-wrap">{plan.compiled_constraints}</p>
                </div>
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

function BuildResultView({ result }: { result: any }) {
  const build = result as BuildResult
  const criteria = build.quality_gate_criteria || []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-tron-400 uppercase tracking-wider">Quality Gates</h4>
        {typeof build.quality_gates_passed === 'boolean' && (
          <div className={`flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded ${build.quality_gates_passed ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
            {build.quality_gates_passed ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
            {build.quality_gates_passed ? 'PASSED' : 'FAILED'}
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        {criteria.map((c, i) => (
          <div key={i} className="flex items-center justify-between p-2 bg-tron-900/40 rounded border border-tron-800/50">
            <div className="flex items-center gap-2 min-w-0">
              {c.passed ? (
                <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />
              ) : (
                <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />
              )}
              <span className="text-sm text-tron-200 truncate">{c.gate}</span>
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-4">
               <span className={`text-xs font-mono ${c.passed ? 'text-tron-300' : 'text-red-300'}`}>
                 {c.actual} / {c.threshold}
               </span>
            </div>
          </div>
        ))}
        {criteria.length === 0 && <p className="text-xs text-tron-500 italic">No criteria evaluated</p>}
      </div>

      {build.validation && (
        <div className="pt-2 border-t border-tron-800">
          <div className="flex items-center gap-2 mb-1">
            {build.validation.ok ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
            ) : (
              <XCircle className="w-3.5 h-3.5 text-red-500" />
            )}
            <h4 className="text-xs font-semibold text-tron-300">Repo Validation</h4>
          </div>
          {!build.validation.ok && build.validation.log_tail && (
            <pre className="text-[10px] bg-red-900/10 p-2 rounded text-red-400/80 overflow-auto max-h-32 whitespace-pre-wrap">
              {build.validation.log_tail}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function EvolveArtifactView({ artifact }: { artifact: any }) {
  const evolve = artifact as EvolveArtifact
  return (
    <div className="space-y-4">
      {evolve.directive && (
        <div>
          <h4 className="text-xs font-semibold text-tron-400 uppercase tracking-wider mb-1">Directive</h4>
          <p className="text-sm text-tron-200 leading-relaxed italic">"{evolve.directive}"</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="px-3 py-2 bg-tron-900/40 rounded border border-tron-800/50">
          <div className="text-[10px] text-tron-500 uppercase font-bold tracking-tight">Findings</div>
          <div className="text-lg font-bold text-tron-100">{evolve.findings_count ?? 0}</div>
        </div>
        <div className="px-3 py-2 bg-tron-900/40 rounded border border-tron-800/50">
          <div className="text-[10px] text-tron-500 uppercase font-bold tracking-tight">Duration</div>
          <div className="text-lg font-bold text-tron-100">{evolve.duration_seconds?.toFixed(1) ?? 0}s</div>
        </div>
      </div>

      {evolve.errors && (
        <div className="p-3 bg-red-900/10 border border-red-900/30 rounded-lg">
          <div className="flex items-center gap-2 text-red-400 mb-1">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-xs font-bold uppercase">Errors Encountered</span>
          </div>
          <p className="text-xs text-red-300/80">{evolve.errors}</p>
        </div>
      )}

      {evolve.findings && evolve.findings.length > 0 && (
        <div className="pt-2 border-t border-tron-800">
           <h4 className="text-xs font-semibold text-tron-400 uppercase tracking-wider mb-2">Recent Changes</h4>
           <div className="space-y-1">
             {evolve.findings.slice(0, 3).map((f, i) => (
               <div key={i} className="text-xs text-tron-300 flex gap-2">
                 <span className="text-accent">•</span>
                 <span className="truncate">{f.description || f.title || 'Artifact modification'}</span>
               </div>
             ))}
             {evolve.findings.length > 3 && (
               <div className="text-[10px] text-tron-500 ml-4">
                 + {evolve.findings.length - 3} more entries
               </div>
             )}
           </div>
        </div>
      )}
    </div>
  )
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [showGithub, setShowGithub] = useState(false)
  const [activeTab, setActiveTab] = useState<'overview' | 'graph'>('overview')
  const { data: project, refetch: refetchProject } = usePolling(() => api.getProject(id!), 15000, [id])
  const { data: audits, refetch } = usePolling(
    () => api.listAudits({ project_id: id!, page_size: 50 }),
    4000,
    [id],
  )
  const [scanning, setScanning] = useState(false)
  const [buildBusy, setBuildBusy] = useState(false)
  const [evolveBusy, setEvolveBusy] = useState(false)
  const [excludeGlobsText, setExcludeGlobsText] = useState('')
  const [testGlobsText, setTestGlobsText] = useState('')
  const [pathFilterBusy, setPathFilterBusy] = useState(false)

  async function handleGithubSelect(repo: api.GithubRepo) {
    if (!project) return
    try {
      await api.updateProject(project.id, {
        repo_url: repo.html_url,
        name: repo.name,
      })
      await refetchProject()
      setShowGithub(false)
    } catch (err: any) {
      alert('Failed to link repository: ' + err.message)
    }
  }

  const auditItems = audits?.items ?? []
  const latestAudit = auditItems.length > 0 ? auditItems[0] : null; // Safely access latestAudit
  const isRunning = auditItems.some(a => a.status === 'running' || a.status === 'queued');

  const completedAudits = auditItems.filter(a => a.status === 'completed')
  const totalFindings = completedAudits.reduce((s, a) => s + a.findings_total, 0)
  const totalCritical = completedAudits.reduce((s, a) => s + a.findings_critical, 0)
  const cleanScans = completedAudits.filter(a => a.findings_total === 0).length
  const avgDuration = completedAudits
    .filter(a => a.completed_at)
    .reduce((s, a) => {
      const dur = (new Date(a.completed_at!).getTime() - new Date(a.started_at).getTime()) / 1000
      return s + dur
    }, 0) / (completedAudits.filter(a => a.completed_at).length || 1)

  const trendData = [...completedAudits].reverse().slice(-10).map((a, i) => ({
    scan: `#${i + 1}`,
    total: a.findings_total,
    critical: a.findings_critical,
    high: a.findings_high,
    date: new Date(a.created_at).toLocaleDateString(),
  }))

  const latestSevData = latestAudit ? [
    { name: 'Critical', value: latestAudit.findings_critical, fill: SEV_COLORS.critical },
    { name: 'High', value: latestAudit.findings_high, fill: SEV_COLORS.high },
    { name: 'Medium', value: latestAudit.findings_medium, fill: SEV_COLORS.medium },
    { name: 'Low', value: latestAudit.findings_low, fill: SEV_COLORS.low },
  ] : []

  async function handleScan() {
    if (!project) return
    setScanning(true)
    try {
      const audit = await api.createAudit({
        project_id: project.id,
        branch: project.default_branch,
        trigger_type: 'manual',
      })
      refetch()
      navigate(`/audits/${audit.id}`)
    } finally {
      setScanning(false)
    }
  }

  async function handleBuild() {
    if (!project) return
    const task = window.prompt('BUILD task (min 3 characters)', 'Address findings from last audit')
    if (task == null) return
    const t = task.trim()
    if (t.length < 3) return
    setBuildBusy(true)
    try {
      await api.startBuildWorkflow(project.id, t)
      window.alert('Build workflow started. Refresh this page in a minute to see last build results.')
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Build start failed')
    } finally {
      setBuildBusy(false)
    }
  }

  async function handleEvolve() {
    if (!project) return
    const directive = window.prompt(
      'EVOLVE directive (min 3 characters)',
      'Reduce tech debt and harden security-sensitive paths',
    )
    if (directive == null) return
    const d = directive.trim()
    if (d.length < 3) return
    setEvolveBusy(true)
    try {
      await api.startEvolveWorkflow(project.id, d)
      window.alert('Evolve workflow started. Refresh this page in a minute to see evolve results.')
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Evolve start failed')
    } finally {
      setEvolveBusy(false)
    }
  }

  const planArtifact = project?.plan_artifact_json
  const lastBuild = project?.last_build_result_json
  const evolveArtifact = project?.evolve_artifact_json

  useEffect(() => {
    if (!project) return
    setExcludeGlobsText((project.audit_exclude_globs_json || []).join('\n'))
    setTestGlobsText((project.audit_test_path_globs_json || []).join('\n'))
  }, [
    project?.id,
    project?.audit_exclude_globs_json,
    project?.audit_test_path_globs_json,
  ])

  if (!project) {
    return (
      <div className="p-6 flex items-center justify-center h-64 text-tron-500">
        Loading project...
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/projects" className="p-2 rounded-lg hover:bg-tron-700 text-tron-400 hover:text-white transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold text-white truncate">{project.name}</h1>
          <div className="flex items-center gap-3 mt-1">
            {project.description && (
              <span className="text-tron-400 text-sm truncate">{project.description}</span>
            )}
            <span className="flex items-center gap-1 text-tron-500 text-xs">
              <GitBranch className="w-3 h-3" /> {project.default_branch}
            </span>
            {project.repo_url && (
              <span className="text-tron-500 text-xs font-mono truncate max-w-xs">{project.repo_url}</span>
            )}
            <button 
              onClick={() => setShowGithub(true)}
              className="flex items-center gap-1.5 px-2.5 py-1 bg-white/5 hover:bg-white/10 text-white rounded-lg text-[10px] font-black uppercase tracking-widest border border-white/10 transition-all"
            >
              <Globe className="w-3 h-3" /> Relink Repository
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Link
            to={`/projects/${project.id}/plan`}
            className="flex items-center gap-2 px-4 py-2 bg-tron-700 hover:bg-tron-600 border border-tron-600 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <ClipboardList className="w-4 h-4" /> Plan wizard
          </Link>
          <button
            type="button"
            onClick={handleEvolve}
            disabled={evolveBusy}
            className="flex items-center gap-2 px-4 py-2 bg-tron-700 hover:bg-tron-600 border border-tron-600 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {evolveBusy ? (
              <><RefreshCw className="w-4 h-4 animate-spin" /> Evolve…</>
            ) : (
              <><TrendingUp className="w-4 h-4" /> Run evolve</>
            )}
          </button>
          <button
            type="button"
            onClick={handleBuild}
            disabled={buildBusy}
            className="flex items-center gap-2 px-4 py-2 bg-tron-700 hover:bg-tron-600 border border-tron-600 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {buildBusy ? (
              <><RefreshCw className="w-4 h-4 animate-spin" /> Build…</>
            ) : (
              <><FileCode className="w-4 h-4" /> Run build</>
            )}
          </button>
          <button
            onClick={handleScan}
            disabled={scanning || isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {isRunning ? (
              <><RefreshCw className="w-4 h-4 animate-spin" /> Scanning...</>
            ) : scanning ? (
              <><RefreshCw className="w-4 h-4 animate-spin" /> Starting...</>
            ) : (
              <><Play className="w-4 h-4" /> Run Scan</>
            )}
          </button>
        </div>
      </div>

      {/* Live Feed during scan */}
      {isRunning && latestAudit && (
        <div className="animate-in slide-in-from-top-4 duration-500">
          <LiveAuditStatus auditId={latestAudit.id} />
        </div>
      )}

      {/* Plan / build / evolve */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {planArtifact && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <ClipboardList className="w-4 h-4 text-accent" />
                  <span className="text-sm font-medium text-white">Active Plan</span>
                </div>
              </CardHeader>
              <CardBody>
                <PlanArtifactView artifact={planArtifact} />
              </CardBody>
            </Card>
          )}
          {lastBuild && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <FileCode className="w-4 h-4 text-blue-400" />
                  <span className="text-sm font-medium text-white">Last Build</span>
                </div>
              </CardHeader>
              <CardBody>
                <BuildResultView result={lastBuild} />
              </CardBody>
            </Card>
          )}
          {evolveArtifact && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-green-400" />
                  <span className="text-sm font-medium text-white">Last Evolve</span>
                </div>
              </CardHeader>
              <CardBody>
                <EvolveArtifactView artifact={evolveArtifact} />
              </CardBody>
            </Card>
          )}
        </div>

      <Card>
        <CardHeader className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-accent" />
            <span className="text-sm font-medium text-white">Audit path filters</span>
          </div>
          <p className="text-[11px] text-tron-500 max-w-prose">
            Exclude globs remove paths from the clone scan. Test globs mark matching files so findings
            are tagged (test path). Not a substitute for a pentest.
          </p>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-tron-500 mb-1">Exclude (one glob per line, * and ** ok)</div>
              <textarea
                value={excludeGlobsText}
                onChange={e => setExcludeGlobsText(e.target.value)}
                className="w-full h-24 bg-tron-900 border border-tron-700 rounded-lg px-3 py-2 text-xs text-tron-200 font-mono"
                placeholder={'**/node_modules/**\n**/*.min.js'}
              />
            </div>
            <div>
              <div className="text-xs text-tron-500 mb-1">Test path globs (tag noise)</div>
              <textarea
                value={testGlobsText}
                onChange={e => setTestGlobsText(e.target.value)}
                className="w-full h-24 bg-tron-900 border border-tron-700 rounded-lg px-3 py-2 text-xs text-tron-200 font-mono"
                placeholder={'**/test/**\n**/*_test.py'}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={pathFilterBusy}
              onClick={async () => {
                const ex = excludeGlobsText
                  .split('\n')
                  .map(s => s.trim())
                  .filter(Boolean)
                const te = testGlobsText
                  .split('\n')
                  .map(s => s.trim())
                  .filter(Boolean)
                setPathFilterBusy(true)
                try {
                  await api.updateProject(project.id, {
                    audit_exclude_globs_json: ex.length ? ex : null,
                    audit_test_path_globs_json: te.length ? te : null,
                  })
                  await refetchProject()
                } catch (e) {
                  window.alert(e instanceof Error ? e.message : 'Save failed')
                } finally {
                  setPathFilterBusy(false)
                }
              }}
              className="px-4 py-2 text-xs font-medium bg-tron-700 hover:bg-tron-600 text-white rounded-lg border border-tron-600 disabled:opacity-50"
            >
              {pathFilterBusy ? 'Saving…' : 'Save path filters'}
            </button>
          </div>
        </CardBody>
      </Card>

      {/* Stats Row */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {[
          { label: 'Total Scans', value: completedAudits.length, icon: BarChart3, color: 'text-accent-light' },
          { label: 'Total Findings', value: totalFindings, icon: Bug, color: 'text-orange-400' },
          { label: 'Critical', value: totalCritical, icon: AlertTriangle, color: totalCritical > 0 ? 'text-red-400' : 'text-green-400' },
          { label: 'Clean Scans', value: cleanScans, icon: Shield, color: 'text-green-400' },
          { label: 'Avg Duration', value: `${avgDuration.toFixed(0)}s`, icon: Zap, color: 'text-blue-400' },
        ].map(s => (
          <Card key={s.label}>
            <CardBody className="flex items-center gap-3 py-3">
              <s.icon className={`w-5 h-5 ${s.color} shrink-0`} />
              <div>
                <div className={`text-lg font-bold ${s.color}`}>{s.value}</div>
                <div className="text-xs text-tron-500">{s.label}</div>
              </div>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-tron-800">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-6 py-3 text-sm font-medium transition-colors border-b-2 ${
            activeTab === 'overview'
              ? 'border-accent text-white'
              : 'border-transparent text-tron-500 hover:text-tron-300'
          }`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveTab('graph')}
          className={`px-6 py-3 text-sm font-medium transition-colors border-b-2 ${
            activeTab === 'graph'
              ? 'border-accent text-white'
              : 'border-transparent text-tron-500 hover:text-tron-300'
          }`}
        >
          Dependency Graph
        </button>
      </div>

      {activeTab === 'overview' ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {trendData.length > 1 && (
              <Card>
                <CardHeader>
                  <span className="text-sm font-medium text-white">Findings Trend</span>
                </CardHeader>
                <CardBody>
                  <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={trendData}>
                      <defs>
                        <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="scan" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} />
                      <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }}
                        labelFormatter={(_, payload) => payload?.[0]?.payload?.date || ''}
                      />
                      <Area type="monotone" dataKey="total" stroke="#3b82f6" fill="url(#colorTotal)" strokeWidth={2} />
                      <Area type="monotone" dataKey="critical" stroke="#ef4444" fill="transparent" strokeWidth={1.5} strokeDasharray="4 2" />
                    </AreaChart>
                  </ResponsiveContainer>
                </CardBody>
              </Card>
            )}

            {latestAudit && latestAudit.findings_total > 0 && (
              <Card>
                <CardHeader>
                  <span className="text-sm font-medium text-white">Latest Scan Breakdown</span>
                </CardHeader>
                <CardBody>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={latestSevData} layout="vertical">
                      <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} width={70} />
                      <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }} />
                      <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={20}>
                        {latestSevData.map((entry, i) => (
                          <Cell key={i} fill={entry.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardBody>
              </Card>
            )}
          </div>

          <Card>
            <CardHeader className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">Audit History</span>
              <span className="text-xs text-tron-500">{auditItems.length} runs</span>
            </CardHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-tron-700 text-tron-400 text-xs">
                    <th className="text-left px-5 py-3 font-medium">Audit</th>
                    <th className="text-left px-5 py-3 font-medium">Status</th>
                    <th className="text-left px-5 py-3 font-medium">Progress</th>
                    <th className="text-right px-5 py-3 font-medium">Findings</th>
                    <th className="text-right px-5 py-3 font-medium">Critical</th>
                    <th className="text-right px-5 py-3 font-medium">High</th>
                    <th className="text-right px-5 py-3 font-medium">Duration</th>
                    <th className="text-right px-5 py-3 font-medium">Started</th>
                    <th className="text-right px-5 py-3 font-medium w-8"></th>
                  </tr>
                </thead>
                <tbody>
                  {auditItems.map(a => {
                    const dur = a.completed_at
                      ? ((new Date(a.completed_at).getTime() - new Date(a.started_at).getTime()) / 1000).toFixed(1) + 's'
                      : '—'
                    return (
                      <tr key={a.id} className="border-b border-tron-700/50 hover:bg-tron-700/30 transition-colors group">
                        <td className="px-5 py-3">
                          <Link to={`/audits/${a.id}`} className="text-accent-light hover:underline font-mono text-xs">
                            {a.id.slice(0, 12)}
                          </Link>
                        </td>
                        <td className="px-5 py-3"><StatusBadge status={a.status} /></td>
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-20 h-1.5 bg-tron-700 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${
                                  a.status === 'failed' ? 'bg-red-500' : a.findings_total === 0 && a.status === 'completed' ? 'bg-green-500' : 'bg-accent'
                                }`}
                                style={{ width: `${a.progress}%` }}
                              />
                            </div>
                            <span className="text-xs text-tron-400">{a.progress}%</span>
                          </div>
                        </td>
                        <td className="px-5 py-3 text-right">
                          {a.findings_total === 0 && a.status === 'completed' ? (
                            <span className="text-green-400 font-medium">✓ Clean</span>
                          ) : (
                            <span className="text-white font-medium">{a.findings_total}</span>
                          )}
                        </td>
                        <td className="px-5 py-3 text-right">
                          <span className={a.findings_critical > 0 ? 'text-severity-critical font-medium' : 'text-tron-500'}>
                            {a.findings_critical}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-right">
                          <span className={a.findings_high > 0 ? 'text-severity-high font-medium' : 'text-tron-500'}>
                            {a.findings_high}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-right text-tron-400 text-xs">{dur}</td>
                        <td className="px-5 py-3 text-right text-tron-400 text-xs whitespace-nowrap">
                          {new Date(a.created_at).toLocaleString()}
                        </td>
                        <td className="px-5 py-3 text-right">
                          <Link to={`/audits/${a.id}`} className="text-tron-500 group-hover:text-accent-light transition-colors">
                            <ChevronRight className="w-4 h-4" />
                          </Link>
                        </td>
                      </tr>
                    )
                  })}
                  {auditItems.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-5 py-12 text-center text-tron-500">
                        No audits yet. Click "Run Scan" to start your first audit.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      ) : (
        <DependencyGraph projectId={id!} />
      )}

      {showGithub && (
        <GithubRepoBrowser 
          onSelect={handleGithubSelect}
          onClose={() => setShowGithub(false)}
        />
      )}
    </div>
  )
}
