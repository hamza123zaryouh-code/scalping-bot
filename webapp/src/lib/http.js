export async function readJsonResponse(response) {
  const text = await response.text().catch(() => '')

  if (!text) return {}

  try {
    return JSON.parse(text)
  } catch {
    return {
      error: text.trim() || 'Unexpected server response.',
      rawText: text,
    }
  }
}
