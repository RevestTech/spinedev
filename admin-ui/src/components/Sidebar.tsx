import { Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Folder,
  BarChart3,
  ExternalLink,
  Settings,
} from 'lucide-react'
import clsx from 'clsx'

const navItems = [
  { label: 'Projects', href: '/projects', icon: Folder },
  { label: 'Costs', href: '/costs', icon: BarChart3 },
]

const externalLinks = [
  {
    label: 'Temporal UI',
    href: 'http://localhost:13008',
    icon: ExternalLink,
  },
  { label: 'Grafana', href: 'http://localhost:13010', icon: ExternalLink },
  { label: 'API Docs', href: 'http://localhost:13000/docs', icon: ExternalLink },
]

export function Sidebar() {
  const location = useLocation()

  return (
    <aside className="w-64 bg-sidebar text-white h-screen overflow-y-auto flex flex-col">
      {/* Header */}
      <div className="px-6 py-6 border-b border-gray-700">
        <Link to="/" className="flex items-center gap-2">
          <LayoutDashboard className="w-8 h-8" />
          <span className="text-xl font-bold">Tron</span>
        </Link>
      </div>

      {/* Main Navigation */}
      <nav className="flex-1 px-3 py-6 space-y-2">
        <p className="text-xs font-semibold text-gray-400 px-3 mb-4 uppercase tracking-wider">
          Navigation
        </p>
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = location.pathname === item.href
          return (
            <Link
              key={item.href}
              to={item.href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg transition-colors',
                isActive
                  ? 'bg-accent text-white'
                  : 'text-gray-300 hover:bg-gray-700'
              )}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              <span className="text-sm font-medium">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* External Links */}
      <div className="px-3 py-6 border-t border-gray-700 space-y-2">
        <p className="text-xs font-semibold text-gray-400 px-3 mb-4 uppercase tracking-wider">
          Tools
        </p>
        {externalLinks.map((item) => {
          const Icon = item.icon
          return (
            <a
              key={item.href}
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-gray-300 hover:bg-gray-700 transition-colors group"
            >
              <Icon className="w-5 h-5 flex-shrink-0 group-hover:text-white" />
              <span className="text-sm font-medium group-hover:text-white">
                {item.label}
              </span>
            </a>
          )
        })}
      </div>

      {/* Footer */}
      <div className="px-3 py-4 border-t border-gray-700">
        <a
          href="#"
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-gray-300 hover:bg-gray-700 transition-colors"
        >
          <Settings className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm font-medium">Settings</span>
        </a>
      </div>
    </aside>
  )
}
