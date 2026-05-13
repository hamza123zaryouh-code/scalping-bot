'use client'

export default function BackendStatusNotice({ system }) {
  if (!system?.backendUnavailable) return null

  return (
    <section className="rounded-xl border border-amber-800 bg-amber-950/40 px-5 py-4 text-sm text-amber-100">
      <p className="font-semibold">Backend offline</p>
      <p className="mt-1 text-amber-200">
        {system.healthError || 'The FastAPI bot backend is not responding right now.'}
      </p>
      <p className="mt-2 text-xs text-amber-300">
        Start command: <span className="font-mono">{system.startCommand}</span>
      </p>
    </section>
  )
}
