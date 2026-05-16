import { useEffect, useRef, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import * as api from './api'

type Gate = 'loading' | 'in' | 'out'

export default function SessionGate() {
  const loc = useLocation()
  const [gate, setGate] = useState<Gate>('loading')
  const sessionOk = useRef(false)

  useEffect(() => {
    const onLoginRoute = loc.pathname === '/login'
    // Cookie sessions share the API IP rate bucket; avoid re-probing on every in-app navigation.
    if (sessionOk.current && !onLoginRoute) {
      return
    }

    let alive = true
    setGate('loading')
    void api
      .adminMe()
      .then(() => {
        if (alive) {
          sessionOk.current = true
          setGate('in')
        }
      })
      .catch(() => {
        if (alive) {
          sessionOk.current = false
          setGate('out')
        }
      })
    return () => {
      alive = false
    }
  }, [loc.pathname])

  if (gate === 'loading') {
    return (
      <div className="min-h-screen bg-tron-900 flex items-center justify-center text-tron-400 text-sm">
        Checking session…
      </div>
    )
  }

  const onLoginRoute = loc.pathname === '/login'
  if (gate === 'out' && !onLoginRoute) {
    return <Navigate to="/login" replace />
  }
  if (gate === 'in' && onLoginRoute) {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}
