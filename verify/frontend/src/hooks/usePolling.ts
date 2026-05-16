import { useEffect, useRef, useState, useCallback } from 'react'

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 5000,
  deps: any[] = [],
) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const timer = useRef<ReturnType<typeof setInterval>>()

  const load = useCallback(async () => {
    try {
      const result = await fetcher()
      setData(result)
      setError(null)
    } catch (e: any) {
      setError(e)
    } finally {
      setLoading(false)
    }
  }, deps)

  useEffect(() => {
    setLoading(true)
    load()
    timer.current = setInterval(load, intervalMs)
    return () => clearInterval(timer.current)
  }, [load, intervalMs])

  return { data, error, loading, refetch: load }
}
