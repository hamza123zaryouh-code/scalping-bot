'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import en from './en.json'
import nl from './nl.json'
import ar from './ar.json'

const TRANSLATIONS = { en, nl, ar }
const STORAGE_KEY = 'tj-language'
const DEFAULT_LANG = 'nl'

const I18nContext = createContext(null)

function applyLanguage(lang) {
  document.documentElement.lang = lang
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr'
}

export function I18nProvider({ children }) {
  const [language, setLanguageState] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_LANG
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && saved in TRANSLATIONS) return saved
    return DEFAULT_LANG
  })

  useEffect(() => {
    applyLanguage(language)
  }, [language])

  const setLanguage = useCallback((lang) => {
    if (!(lang in TRANSLATIONS)) return
    localStorage.setItem(STORAGE_KEY, lang)
    applyLanguage(lang)
    setLanguageState(lang)
  }, [])

  const t = useCallback(
    (key, vars = {}) => {
      const dict = TRANSLATIONS[language] ?? TRANSLATIONS[DEFAULT_LANG]
      const parts = key.split('.')
      let value = dict

      for (const part of parts) {
        value = value?.[part]
      }

      if (value === undefined || value === null) return key
      if (typeof value !== 'string') return key

      return value.replace(/\{\{(\w+)\}\}/g, (_, name) => {
        if (vars[name] === undefined || vars[name] === null) return `{{${name}}}`
        return String(vars[name])
      })
    },
    [language]
  )

  const value = useMemo(
    () => ({ language, setLanguage, t }),
    [language, setLanguage, t]
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useTranslation() {
  const context = useContext(I18nContext)
  if (!context) {
    throw new Error('useTranslation must be used inside I18nProvider')
  }
  return context
}

export const LANGUAGES = [
  { code: 'nl', label: 'NL', name: 'Nederlands' },
  { code: 'en', label: 'EN', name: 'English' },
  { code: 'ar', label: 'AR', name: 'العربية' },
]
