import { useState, useEffect } from 'react'
import { 
  Search, Globe, Star, Clock, 
  ChevronRight, X, AlertCircle, RefreshCw, Check
} from 'lucide-react'
import * as api from '../api'
import { cn } from '../utils'

interface Props {
  onSelect: (repo: api.GithubRepo) => void;
  onClose: () => void;
}

export default function GithubRepoBrowser({ onSelect, onClose }: Props) {
  const [repos, setRepos] = useState<api.GithubRepo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [orgName, setOrgName] = useState('')

  useEffect(() => {
    fetchRepos()
  }, [])

  async function fetchRepos(org?: string) {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listGithubRepos(org)
      setRepos(data)
    } catch (err: any) {
      setError(err.message || 'Failed to connect to GitHub. Check your token in settings.')
    } finally {
      setLoading(false)
    }
  }

  const filtered = repos.filter(r => 
    r.full_name.toLowerCase().includes(query.toLowerCase()) ||
    (r.description || '').toLowerCase().includes(query.toLowerCase())
  )

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

        {/* Search & Filter */}
        <div className="p-6 bg-tron-900/40 border-b border-tron-700 space-y-4">
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
          
          <div className="flex gap-2">
             <input 
              type="text"
              placeholder="Organization Name (optional)..."
              className="flex-1 bg-tron-900 border border-tron-700 rounded-xl py-2 px-4 text-xs font-medium text-tron-300 focus:outline-none focus:border-accent"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchRepos(orgName)}
            />
            <button 
              onClick={() => fetchRepos(orgName)}
              className="px-4 py-2 bg-tron-700 hover:bg-tron-600 text-white rounded-xl text-xs font-black uppercase tracking-widest transition-all"
            >
              Fetch
            </button>
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
            <div className="py-20 text-center text-tron-500">
               <p className="text-sm font-bold italic">No repositories found.</p>
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
