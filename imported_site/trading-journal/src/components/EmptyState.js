import Link from 'next/link'

export default function EmptyState({
  icon,
  title = 'Nothing here yet',
  message = 'Add your first trade to start tracking your performance.',
  action,
  secondaryAction,
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900 px-6 py-14 text-center">
      {icon ? (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-800 text-zinc-400">
          {icon}
        </div>
      ) : null}
      <p className="text-base font-semibold text-white">{title}</p>
      <p className="mt-1.5 max-w-xs text-sm text-zinc-500">{message}</p>
      {action && (
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link
            href={action.href}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-500"
          >
            {action.label}
          </Link>
          {secondaryAction && (
            <Link
              href={secondaryAction.href}
              className="rounded-lg border border-zinc-700 px-4 py-2 text-sm font-semibold text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-white"
            >
              {secondaryAction.label}
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
