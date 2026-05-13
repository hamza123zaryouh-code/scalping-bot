/** color: 'default' | 'emerald' | 'red' | 'sky' */
export default function StatCard({ label, value, sub, color = 'default', icon }) {
  const colors = {
    default: 'text-white',
    emerald: 'text-emerald-400',
    red: 'text-red-400',
    sky: 'text-sky-400',
  }
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
      <div className="flex items-start justify-between mb-2">
        <p className="text-zinc-500 text-xs font-medium uppercase tracking-wider">{label}</p>
        {icon && <span className="text-lg">{icon}</span>}
      </div>
      <p className={`text-2xl font-bold ${colors[color]}`}>{value}</p>
      {sub && <p className="text-zinc-600 text-xs mt-1">{sub}</p>}
    </div>
  )
}
