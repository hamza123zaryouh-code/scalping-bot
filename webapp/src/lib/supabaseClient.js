import { createClient } from '@supabase/supabase-js'
import { getSupabaseBrowserConfig } from '@/lib/supabase'

let browserSupabaseClient = null

export function getSupabaseClient() {
  if (browserSupabaseClient) return browserSupabaseClient

  const { supabaseUrl, supabaseAnonKey } = getSupabaseBrowserConfig()

  browserSupabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  })

  return browserSupabaseClient
}
