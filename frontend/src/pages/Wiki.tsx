import { useState, useMemo } from 'react'
import { 
  BookOpen, Shield, ScanSearch, Cpu, CheckCircle2, Server, Globe, Radio, 
  Search, ChevronRight, Info, AlertTriangle, Zap, Terminal, Layers, 
  Target, Activity, Lock, Database, X, Code, Network, ArrowRight, Monitor,
  BarChart3, History, Bug, ChevronDown, ExternalLink, Copy, Key, Settings,
  Clock, GitBranch, TerminalSquare, LayoutDashboard, DollarSign, UserCheck,
  Binary, Wrench, Boxes, GitMerge, FileCode2
} from 'lucide-react'

/* ── Components ── */

const MethodBadge = ({ method }: { method: string }) => {
  const colors: Record<string, string> = {
    'GET': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    'POST': 'bg-green-500/20 text-green-400 border-green-500/30',
    'PROVE': 'bg-accent/20 text-accent-light border-accent/30',
    'SCAN': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    'FAIL': 'bg-red-500/20 text-red-400 border-red-500/30',
    'FLOW': 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    'TECH': 'bg-tron-700 text-tron-100 border-tron-600',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-black border uppercase tracking-widest ${colors[method] || colors['GET']}`}>
      {method}
    </span>
  )
}

const CodeBlock = ({ title, code, language = 'json' }: { title: string, code: string, language?: string }) => {
  return (
    <div className="rounded-xl overflow-hidden border border-tron-700 bg-tron-950 shadow-2xl my-4">
      <div className="bg-tron-800/50 px-4 py-2 flex items-center justify-between border-b border-tron-700">
        <span className="text-[9px] font-black text-tron-500 uppercase tracking-widest">{title}</span>
        <Copy className="w-3 h-3 text-tron-600 hover:text-white cursor-pointer transition-colors" />
      </div>
      <div className="p-4 overflow-x-auto">
        <pre className="text-[11px] font-mono leading-relaxed text-tron-300">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  )
}

const StatusBox = ({ status, label, color }: { status: string, label: string, color: string }) => {
  const colors: Record<string, string> = {
    green: 'bg-green-500/10 text-green-400 border-green-500/20',
    yellow: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
    red: 'bg-red-500/10 text-red-400 border-red-500/20',
    blue: 'bg-accent/10 text-accent-light border-accent/20',
    grey: 'bg-tron-800 text-tron-400 border-tron-700',
  }
  return (
    <div className={`flex items-start gap-4 p-4 rounded-xl border ${colors[color]} transition-all`}>
      <span className={`px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-tighter border ${colors[color]}`}>{status}</span>
      <p className="text-xs font-medium leading-relaxed text-tron-200">{label}</p>
    </div>
  )
}

/* ── Documentation Data ── */

const DOCS_DATA = [
  {
    group: 'PLATFORM GUIDE',
    items: [
      {
        id: 'overview',
        title: 'Platform Overview',
        icon: <Shield className="w-4 h-4" />,
        content: (
          <div className="space-y-12">
            <header>
              <h2 className="text-5xl font-black text-white tracking-tighter mb-6">How Tron Works</h2>
              <p className="text-tron-300 text-xl leading-relaxed">
                In plain English: Tron is a system that scans your code to find security vulnerabilities and 
                performance bottlenecks. Unlike a standard "scanner" that just flags suspicious words, Tron 
                actually **tries to exploit the code** in a safe, isolated container to see if it's a real bug 
                or just a false alarm.
              </p>
            </header>

            <section className="space-y-6">
              <h3 className="text-2xl font-black text-white tracking-tight pt-8 border-t border-tron-800">The 3-Step Process</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                <div className="space-y-3">
                  <div className="p-3 bg-tron-800 rounded-2xl w-fit text-accent shadow-xl"><ScanSearch className="w-6 h-6" /></div>
                  <h4 className="text-white font-black text-sm uppercase tracking-widest underline decoration-accent underline-offset-4">1. The Scan</h4>
                  <p className="text-xs text-tron-400 leading-relaxed">We break the code into small pieces and send them to specialized AI agents. One looks for security, another for performance, another for compliance.</p>
                </div>
                <div className="space-y-3">
                  <div className="p-3 bg-tron-800 rounded-2xl w-fit text-red-400 shadow-xl"><TerminalSquare className="w-6 h-6" /></div>
                  <h4 className="text-white font-black text-sm uppercase tracking-widest underline decoration-red-400 underline-offset-4">2. The Proof</h4>
                  <p className="text-xs text-tron-400 leading-relaxed">If an agent thinks it found a bug, Tron spins up a "Sandbox" (a tiny, temporary computer). It runs a test script to see if the bug can actually be triggered.</p>
                </div>
                <div className="space-y-3">
                  <div className="p-3 bg-tron-800 rounded-2xl w-fit text-green-400 shadow-xl"><UserCheck className="w-6 h-6" /></div>
                  <h4 className="text-white font-black text-sm uppercase tracking-widest underline decoration-green-400 underline-offset-4">3. The Verdict</h4>
                  <p className="text-xs text-tron-400 leading-relaxed">Only proven or highly-likely bugs make it to the final report. This saves you time by ignoring the "fake" warnings that other tools usually spit out.</p>
                </div>
              </div>
            </section>
            
            <section className="p-8 bg-tron-800/40 rounded-3xl border border-tron-700">
               <h4 className="text-white font-black text-sm uppercase mb-4 flex items-center gap-2"><Info className="w-4 h-4 text-accent" /> Why do we have 8 agents?</h4>
               <p className="text-sm text-tron-300 leading-relaxed">
                 Think of it like a professional peer-review. You wouldn't ask a security expert to check your database performance. 
                 Tron has specialists for: <strong>Security, Performance, DevOps/Builds, Quality, Compliance, Documentation, and Memory</strong>. 
                 The 8th agent, the <strong>Manager</strong>, gathers all their notes and presents one unified report.
               </p>
            </section>
          </div>
        )
      }
    ]
  },
  {
    group: 'DEEP TECHNOLOGY',
    items: [
      {
        id: 'temporal',
        title: 'Temporal Orchestration',
        icon: <Activity className="w-4 h-4" />,
        content: (
          <div className="space-y-8">
            <header>
              <MethodBadge method="TECH" />
              <h2 className="text-4xl font-black text-white tracking-tighter mt-4">Durable Execution</h2>
              <p className="text-tron-300 text-lg leading-relaxed">How we ensure an audit never crashes or loses its place.</p>
            </header>

            <section className="space-y-6">
              <p className="text-sm text-tron-400 leading-relaxed">
                Tron uses <strong>Temporal.io</strong> as its workflow engine. Traditional systems use simple cron jobs or stateless APIs. 
                Temporal allows us to write "Stateful Workflows" that can run for hours.
              </p>
              <ul className="space-y-4 ml-4">
                <li className="text-xs text-tron-300 flex items-start gap-3">
                   <div className="w-1.5 h-1.5 rounded-full bg-accent mt-1.5" />
                   <div><strong>Fault Tolerance:</strong> If the worker server hosting an audit reboots, Temporal "replays" the history and resumes exactly where it left off.</div>
                </li>
                <li className="text-xs text-tron-300 flex items-start gap-3">
                   <div className="w-1.5 h-1.5 rounded-full bg-accent mt-1.5" />
                   <div><strong>Parallelism:</strong> We use Temporal's `asyncio.gather` equivalent to run all 8 ISO agents at the exact same millisecond across a cluster of workers.</div>
                </li>
              </ul>
              <CodeBlock title="WORKFLOW DEFINITION (INTERNAL)" code={`@workflow.defn\nclass AuditWorkflow:\n    @workflow.run\n    async def run(self, input: AuditInput):\n        # 1. Gather context (L1)\n        # 2. Run Agents (L2) in parallel\n        # 3. Execute proofs (L3)\n        # 4. Synthesize results (L4)`} />
            </section>
          </div>
        )
      },
      {
        id: 'sandbox-tech',
        title: 'Sandbox Isolation',
        icon: <Terminal className="w-4 h-4" />,
        content: (
          <div className="space-y-10">
             <header>
              <MethodBadge method="TECH" />
              <h2 className="text-4xl font-black text-white tracking-tighter mt-4">The Sandbox Manager</h2>
              <p className="text-tron-300 text-lg leading-relaxed">Docker-in-Docker isolation and gRPC communication.</p>
            </header>

            <section className="space-y-6">
              <p className="text-sm text-tron-400 leading-relaxed">
                Layer 3 (Execution Proof) relies on <code>tron-sandbox</code>. This is a dedicated service that communicates 
                via <strong>gRPC (Protocol Buffers)</strong> for low-latency command execution.
              </p>
              <div className="p-6 bg-tron-950 rounded-2xl border border-tron-800 space-y-4 font-mono text-[11px]">
                 <div className="text-tron-600"># Engineering Specs:</div>
                 <div className="text-white">Container Runtime: <span className="text-accent">Docker API</span></div>
                 <div className="text-white">Default Image: <span className="text-accent">python:3.11-slim</span></div>
                 <div className="text-white">Resource Limits: <span className="text-red-400">128MB RAM | 0.5 CPU Units</span></div>
                 <div className="text-white">Network: <span className="text-red-400">INTERNAL_ONLY (Disabled by default)</span></div>
              </div>
              <p className="text-xs text-tron-500 italic">
                Security note: The sandbox service runs with a local Docker socket volume mount, allowing it to dynamically pull 
                and spin up target images specified in the project's Dockerfiles.
              </p>
            </section>
          </div>
        )
      },
      {
        id: 'zero-drift',
        title: 'Zero-Drift Baseline',
        icon: <Database className="w-4 h-4" />,
        content: (
          <div className="space-y-10">
            <header>
              <MethodBadge method="TECH" />
              <h2 className="text-4xl font-black text-white tracking-tighter mt-4">Baseline Persistence</h2>
              <p className="text-tron-300 text-lg leading-relaxed">How we compare today's run with yesterday's findings.</p>
            </header>

            <section className="space-y-6">
               <p className="text-sm text-tron-400 leading-relaxed">
                 Tron stores every finding as a <strong>Fingerprint</strong> in PostgreSQL. This fingerprint is a 
                 deterministic hash of the vulnerability type, the file path, and the specific code context.
               </p>
               <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-5 bg-tron-800/40 border border-tron-700 rounded-2xl">
                     <div className="text-white font-bold text-xs uppercase mb-2">Finding Fingerprint</div>
                     <div className="p-3 bg-black/40 rounded-lg font-mono text-[10px] text-accent">sha256(vuln_type + path + hash(code))</div>
                  </div>
                  <div className="p-5 bg-tron-800/40 border border-tron-700 rounded-2xl">
                     <div className="text-white font-bold text-xs uppercase mb-2">Reconciliation Logic</div>
                     <p className="text-[11px] text-tron-500">If a fingerprint exists in the database but is NOT found in the current run, it's marked as "Resolved".</p>
                  </div>
               </div>
            </section>
          </div>
        )
      }
    ]
  },
  {
    group: 'RESOURCES',
    items: [
      {
        id: 'status-values',
        title: 'Status Dictionary',
        icon: <Binary className="w-4 h-4" />,
        content: (
          <div className="space-y-12">
            <header>
              <h2 className="text-4xl font-black text-white tracking-tighter">System Terminology</h2>
            </header>

            <div className="space-y-4">
              <StatusBox status="PROVEN" color="green" label="The bug was successfully triggered in the sandbox. This is a 100% confirmed security threat." />
              <StatusBox status="VERIFIED" color="blue" label="Multiple AI agents agree this is a bug, but it couldn't be physically triggered (e.g., hardcoded secret)." />
              <StatusBox status="DRIFT" color="red" label="Internal system error. The agent's reasoning style has changed too much since the last update." />
              <StatusBox status="REJECTED" color="grey" label="Human or agent consensus determined this finding was a mistake. Tron will ignore this pattern in the future." />
            </div>
          </div>
        )
      }
    ]
  }
]

export default function Wiki() {
  const [activeId, setActiveId] = useState('overview')
  const [searchQuery, setSearchQuery] = useState('')

  const activeContent = useMemo(() => {
    for (const group of DOCS_DATA) {
      const item = group.items.find(i => i.id === activeId)
      if (item) return item
    }
    return DOCS_DATA[0].items[0]
  }, [activeId])

  const filteredDocs = useMemo(() => {
    if (!searchQuery) return DOCS_DATA
    return DOCS_DATA.map(group => ({
      ...group,
      items: group.items.filter(item => 
        item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.id.toLowerCase().includes(searchQuery.toLowerCase())
      )
    })).filter(group => group.items.length > 0)
  }, [searchQuery])

  return (
    <div className="flex h-full w-full bg-tron-900 text-tron-300 overflow-hidden font-sans select-none">
      
      {/* ── Sidebar ── */}
      <aside className="w-80 shrink-0 bg-tron-800/40 border-r border-tron-700 flex flex-col shadow-2xl z-20">
        <div className="p-10 border-b border-tron-700">
           <div className="flex items-center gap-4">
              <div className="p-3 bg-accent rounded-2xl shadow-[0_0_40px_rgba(37,99,235,0.4)]">
                 <BookOpen className="w-6 h-6 text-white" />
              </div>
              <h1 className="text-2xl font-black text-white tracking-tighter">TRON <span className="text-accent">DOCS</span></h1>
           </div>
        </div>

        <div className="p-6">
           <div className="relative group">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-tron-600 group-focus-within:text-accent transition-colors" />
              <input 
                type="text"
                placeholder="Find technical detail..."
                className="w-full bg-tron-950/60 border-2 border-tron-800 rounded-2xl py-4 pl-12 pr-4 text-xs font-black text-white focus:outline-none focus:border-accent transition-all placeholder:text-tron-700 shadow-inner"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
           </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-4 pb-20 space-y-12 scrollbar-hide">
           {filteredDocs.map(group => (
             <div key={group.group}>
                <p className="text-[10px] font-black text-tron-600 uppercase tracking-[0.4em] mb-6 ml-6">{group.group}</p>
                <div className="space-y-1.5">
                   {group.items.map(item => (
                     <button
                       key={item.id}
                       onClick={() => setActiveId(item.id)}
                       className={`w-full flex items-center gap-4 px-6 py-3 rounded-2xl transition-all group ${
                         activeId === item.id 
                           ? 'bg-accent shadow-[0_20px_40px_rgba(37,99,235,0.3)] translate-x-2' 
                           : 'hover:bg-tron-700/50'
                       }`}
                     >
                       <span className={`flex items-center gap-4 text-[13px] font-semibold tracking-wide ${
                         activeId === item.id ? '!text-white' : 'text-tron-300 group-hover:text-white'
                       }`}>
                         <span className={activeId === item.id ? '!text-white' : 'text-tron-600'}>
                           {item.icon}
                         </span>
                         {item.title}
                       </span>
                     </button>
                   ))}
                </div>
             </div>
           ))}
        </nav>
      </aside>

      {/* ── Main Content ── */}
      <main className="flex-1 overflow-y-auto bg-tron-900/40 relative selection:bg-accent/40 selection:text-white">
        <div className="w-full p-12 lg:p-24 lg:pr-12 animate-in fade-in slide-in-from-right-8 duration-700">
          
          <div className="flex flex-col xl:flex-row gap-24 items-start">
            <div className="flex-1 min-w-0">
              <div className="breadcrumbs flex items-center gap-3 mb-16 text-[10px] font-black text-tron-600 uppercase tracking-[0.4em]">
                 <span>TRON ENGINEERING</span>
                 <ChevronRight className="w-3 h-3" />
                 <span className="text-accent">{activeContent.title}</span>
              </div>
              {activeContent.content}
            </div>

            {/* ── Contextual Sidebar ── */}
            <div className="w-full xl:w-80 shrink-0 sticky top-0 space-y-10">
               <div className="p-10 bg-tron-800/40 border-2 border-tron-700 rounded-[3rem] shadow-2xl relative overflow-hidden group">
                  <div className="absolute top-0 left-0 w-2 h-full bg-accent group-hover:w-3 transition-all" />
                  <h5 className="text-white font-black text-[11px] uppercase tracking-[0.3em] mb-6 flex items-center gap-3">
                    <Info className="w-5 h-5 text-accent" /> Engineering Insight
                  </h5>
                  <p className="text-[13px] text-tron-300 font-bold leading-relaxed italic">
                    "Internal logic: Verification always outranks probabilistic detection. If L3 can't trigger it, the severity is capped automatically."
                  </p>
                  <div className="mt-10 flex flex-col gap-2 pt-6 border-t border-tron-700">
                    <span className="text-[10px] font-black text-tron-600 uppercase tracking-widest">Stack Stability</span>
                    <span className="text-xs text-green-400 font-black uppercase tracking-tighter flex items-center gap-2">
                       <Activity className="w-3.5 h-3.5" /> v5.3.0-STABLE
                    </span>
                  </div>
               </div>
               
               <div className="p-10 bg-accent/5 border-2 border-accent/20 rounded-[3rem] shadow-inner group hover:bg-accent/10 transition-all cursor-pointer">
                  <div className="flex items-center gap-3 mb-6">
                    <Zap className="w-6 h-6 text-accent group-hover:scale-125 transition-transform" />
                    <span className="text-[11px] font-black text-white uppercase tracking-[0.2em]">Dev Guide</span>
                  </div>
                  <p className="text-xs text-accent-light font-black tracking-tight leading-relaxed uppercase opacity-80">
                    Temporal workers require a persistent connection to Postgres and Redis to manage workflow state.
                  </p>
               </div>
            </div>
          </div>

          <div className="mt-48 pt-12 border-t-2 border-tron-800 flex justify-between items-center text-tron-600 font-black text-[10px] uppercase tracking-[0.5em]">
             <span>Tron Internal Engineering Handbook</span>
             <button 
               onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
               className="hover:text-white transition-colors flex items-center gap-3"
             >
               Scroll to Top <ChevronDown className="w-3 h-3 rotate-180" />
             </button>
          </div>
        </div>
      </main>
    </div>
  )
}
