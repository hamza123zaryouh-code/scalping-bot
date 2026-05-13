export const SYMBOL_CONFIGS = {
  XAUUSD: { contractSize: 100, profitCurrency: 'USD' },
}

export const DEFAULT_SYMBOL_CONFIG = { contractSize: 1, profitCurrency: 'EUR' }

export function getSymbolConfig(symbol) {
  return SYMBOL_CONFIGS[String(symbol || '').toUpperCase()] ?? DEFAULT_SYMBOL_CONFIG
}
