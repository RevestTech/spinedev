import { Link, useLocation } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

export function Header() {
  const location = useLocation()

  // Build breadcrumbs from pathname
  const pathSegments = location.pathname
    .split('/')
    .filter((segment) => segment && segment !== 'admin')
  const breadcrumbs = [
    { label: 'Tron', href: '/' },
    ...pathSegments.map((segment, index) => ({
      label: segment.charAt(0).toUpperCase() + segment.slice(1),
      href: '/' + pathSegments.slice(0, index + 1).join('/'),
    })),
  ]

  return (
    <div className="bg-white border-b border-gray-200 py-4 px-6">
      <div className="flex items-center gap-2 text-sm">
        {breadcrumbs.map((crumb, index) => (
          <div key={crumb.href} className="flex items-center gap-2">
            <Link
              to={crumb.href}
              className={
                index === breadcrumbs.length - 1
                  ? 'font-medium text-gray-900'
                  : 'text-gray-600 hover:text-gray-900'
              }
            >
              {crumb.label}
            </Link>
            {index < breadcrumbs.length - 1 && (
              <ChevronRight className="w-4 h-4 text-gray-400" />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
