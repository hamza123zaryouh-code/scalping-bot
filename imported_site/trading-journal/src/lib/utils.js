export function pnlColor(value) {
  if (value > 0) return 'text-emerald-400'
  if (value < 0) return 'text-red-400'
  return 'text-zinc-400'
}

export function typeBadgeClass(type) {
  return type === 'Buy' ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'
}

export function truncate(text, maxLength = 80) {
  if (!text) return ''
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

export function formatDate(dateString) {
  if (!dateString) return ''
  return new Date(`${dateString}T00:00:00`).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function getMonthName(date) {
  return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
}
