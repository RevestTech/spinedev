import { useState } from 'react'
import { NavLink, Link, useNavigate } from 'react-router-dom'
import { 
  LayoutDashboard, FolderGit2, ScanSearch, GitBranch, DollarSign, 
  HeartPulse, Settings, Shield, Radio, LogOut, BookOpen,
  ChevronDown, ChevronRight, Search, Zap, Activity, Info, Database,
  Terminal, Layers, Target, Lock, Globe, Cpu
} from 'lucide-react'
import { cn } from '../utils'
import * as api from '../api'

interface NavItem {
  to: string;
  label: string;
  icon: any;
  end?: boolean;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    title: 'CORE PLATFORM',
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Overview', end: true },
      { to: '/projects', icon: FolderGit2, label: 'Projects' },
      { to: '/audits', icon: ScanSearch, label: 'Audits' },
    ],
  },
  {
    title: 'LIVE OPERATIONS',
    items: [
      { to: '/live', icon: Radio, label: 'Live Events' },
      { to: '/workflows', icon: GitBranch, label: 'Workflows' },
    ],
  },
  {
    title: 'RESOURCES',
    items: [
      { to: '/costs', icon: DollarSign, label: 'Cost Analysis' },
      { to: '/health', icon: HeartPulse, label: 'System Health' },
      { to: '/wiki', icon: BookOpen, label: 'Tron Wiki' },
      { to: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
]

export default function Sidebar() {
  const navigate = useNavigate()
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    'CORE PLATFORM': true,
    'LIVE OPERATIONS': true,
    'RESOURCES': true,
  })

  const toggleGroup = (title: string) => {
    setOpenGroups(prev => ({ ...prev, [title]: !prev[title] }))
  }

  async function handleLogout() {
    try {
      await api.adminLogout()
    } catch { /* ignore */ }
    localStorage.removeItem('tron-api-key')
    navigate('/login', { replace: true })
  }

  return (
    <aside 
      className={cn(
        "h-screen bg-tron-800 border-r border-tron-700 flex flex-col transition-all duration-300 shadow-2xl z-30 shrink-0",
        isCollapsed ? "w-20" : "w-72"
      )}
    >
      {/* Brand Header */}
      <div className="p-6 border-b border-tron-700 flex items-center justify-between overflow-hidden">
        {!isCollapsed ? (
          <div className="flex items-center gap-3 animate-in fade-in duration-300">
            <div className="p-2 bg-accent rounded-xl shadow-lg shadow-accent/20">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-black text-white tracking-tighter uppercase italic">TRON <span className="text-accent">OS</span></h1>
              <p className="text-[9px] font-bold text-tron-500 uppercase tracking-widest leading-none">Enterprise QA</p>
            </div>
          </div>
        ) : (
          <div className="mx-auto p-2 bg-accent rounded-xl">
            <Shield className="w-5 h-5 text-white" />
          </div>
        )}
      </div>

      {/* Nav Content */}
      <div className="flex-1 overflow-y-auto px-4 py-8 space-y-8 scrollbar-hide">
        {navGroups.map(group => {
          const isOpen = openGroups[group.title]
          return (
            <div key={group.title} className="space-y-2">
              {!isCollapsed && (
                <button 
                  onClick={() => toggleGroup(group.title)}
                  className="w-full flex items-center justify-between px-4 py-1 text-[10px] font-black text-tron-600 uppercase tracking-[0.3em] hover:text-tron-400 transition-colors"
                >
                  {group.title}
                  {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                </button>
              )}

              {(isOpen || isCollapsed) && (
                <div className="space-y-1">
                  {group.items.map(item => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      end={item.end}
                      className={({ isActive }) => cn(
                        "flex items-center gap-4 px-5 py-3 rounded-2xl text-sm font-black tracking-tight transition-all relative group",
                        isCollapsed ? "justify-center" : "",
                        isActive 
                          ? "bg-accent !text-white shadow-[0_15px_30px_rgba(37,99,235,0.3)] translate-x-1" 
                          : "text-tron-200 hover:bg-tron-700/50 hover:text-white"
                      )}
                      title={isCollapsed ? item.label : undefined}
                    >
                      {({ isActive }) => (
                        <>
                          <item.icon className={cn("w-5 h-5 shrink-0", isCollapsed ? "" : isActive ? "!text-white" : "text-tron-400 group-hover:text-white")} />
                          {!isCollapsed && <span>{item.label}</span>}
                          {isActive && !isCollapsed && (
                            <div className="absolute right-3 w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                          )}
                        </>
                      )}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Footer / System Status */}
      <div className="p-6 bg-tron-950/40 border-t border-tron-700 space-y-4">
        {!isCollapsed && (
          <div className="p-4 bg-tron-900/50 rounded-2xl border border-tron-700 space-y-3">
             <div className="flex items-center gap-2 text-[10px] font-black text-tron-500 uppercase tracking-widest">
               <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse shadow-[0_0_10px_rgba(34,197,94,0.5)]" /> 
               Agent Pulse
             </div>
             <div className="space-y-2 text-[9px] font-black tracking-tight text-tron-500">
                <div className="flex justify-between"><span>OSV FEED</span><span className="text-green-500">ONLINE</span></div>
                <div className="flex justify-between"><span>SANDBOX</span><span className="text-green-500">READY</span></div>
             </div>
          </div>
        )}

        <div className="space-y-2">
          <button
            type="button"
            onClick={() => void handleLogout()}
            className={cn(
              "w-full flex items-center justify-center gap-3 py-3 rounded-2xl text-xs font-black uppercase tracking-widest transition-all",
              "bg-tron-800 border border-tron-700 text-tron-400 hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/30"
            )}
          >
            <LogOut className="w-4 h-4" />
            {!isCollapsed && "Terminate Session"}
          </button>
          
          <div className="flex items-center justify-between px-2">
            {!isCollapsed && (
              <span className="text-[10px] font-bold text-tron-600 uppercase tracking-tighter italic">Tron Enterprise v5.4</span>
            )}
            <button 
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-1.5 rounded-lg hover:bg-tron-700 text-tron-600 transition-colors"
            >
              {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}

function ChevronLeft({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" width="16" height="16">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M15 19l-7-7 7-7" />
    </svg>
  );
}
