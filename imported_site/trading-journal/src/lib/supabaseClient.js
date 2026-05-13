import { createClient } from '@supabase/supabase-js'
import { getSupabaseConfig } from '@/lib/supabase'

let browserSupabaseClient = null

export function getSupabaseClient() {
  if (browserSupabaseClient) return browserSupabaseClient

  const { supabaseUrl, supabaseAnonKey } = getSupabaseConfig()

  browserSupabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  })

  return browserSupabaseClient
}
