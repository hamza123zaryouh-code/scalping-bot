'use client'

import { formatCurrency } from '@/lib/tradeUtils'

export default function MiniChart({ data = [], height = 80, title, currency = 'EUR' }) {
  if (!data.length) return null

  const maxAbs = Math.max(...data.map((d) => Math.abs(d.value)), 0.01)

  return (
    <div>
      {title && (
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-zinc-500">{title}</p>
      )}
      <div className="flex items-end gap-1.5" style={{ height: height + 28 }}>
        {data.map((item, i) => {
          const barH = (Math.abs(item.value) / maxAbs) * height
          const isPositive = item.value >= 0
          const formatted = formatCurrency(item.value, currency)
          const label = `${item.label}: ${formatted}`

          return (
            <div key={i} className="relative flex flex-1 flex-col items-center justify-end gap-1 group">
              <div className="pointer-events-none absolute bottom-full mb-1 hidden rounded bg-zinc-800 px-2 py-1 text-xs whitespace-nowrap text-white group-hover:block z-10">
                {formatted}
              </div>
              <div
                className={`w-full rounded-t-sm transition-all duration-300 ${
                  isPositive ? 'bg-emerald-500' : 'bg-red-500'
                }`}
                style={{ height: Math.max(barH, 2) }}
                title={label}
              />
              <span className="w-full truncate text-center text-xs text-zinc-600">{item.label}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
