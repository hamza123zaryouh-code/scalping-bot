// Fixed indicative USD->EUR rate. Used only when the profile has no custom rate.
export const USD_TO_EUR_RATE = 0.92

export function getUsdToEurRate(value = USD_TO_EUR_RATE) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : USD_TO_EUR_RATE
}

export function convertCurrency(amount, fromCurrency, toCurrency, usdToEurRate = USD_TO_EUR_RATE) {
  const value = Number(amount || 0)
  const from = String(fromCurrency || 'EUR').toUpperCase()
  const to = String(toCurrency || 'EUR').toUpperCase()
  const rate = getUsdToEurRate(usdToEurRate)

  if (from === to) return value
  if (from === 'USD' && to === 'EUR') return value * rate
  if (from === 'EUR' && to === 'USD') return value / rate
  return value
}

export function convertToEur(amount, fromCurrency, usdToEurRate = USD_TO_EUR_RATE) {
  return convertCurrency(amount, fromCurrency, 'EUR', usdToEurRate)
}

export function convertFromEur(amount, toCurrency, usdToEurRate = USD_TO_EUR_RATE) {
  return convertCurrency(amount, 'EUR', toCurrency, usdToEurRate)
}
