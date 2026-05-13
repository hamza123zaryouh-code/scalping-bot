export default function LoadingSpinner({ size = 'md', center = false }) {
  const sizes = { sm: 'h-4 w-4 border-2', md: 'h-8 w-8 border-2', lg: 'h-12 w-12 border-3' }
  const spin = (
    <div className={`${sizes[size]} rounded-full border-zinc-700 border-t-emerald-500 animate-spin`} />
  )
  if (center) return <div className="flex justify-center items-center py-20">{spin}</div>
  return spin
}
