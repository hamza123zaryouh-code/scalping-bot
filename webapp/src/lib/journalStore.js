import { promises as fs } from 'fs'
import path from 'path'

const STORE_DIRECTORY = path.join(process.cwd(), '.local-data')
const STORE_PATH = path.join(STORE_DIRECTORY, 'journal-store.json')

const DEFAULT_STORE = {
  profiles: {},
  trades: [],
  reviews: [],
}

function cloneDefaultStore() {
  return JSON.parse(JSON.stringify(DEFAULT_STORE))
}

async function ensureStoreDirectory() {
  await fs.mkdir(STORE_DIRECTORY, { recursive: true })
}

async function writeStore(store) {
  await ensureStoreDirectory()
  const tempPath = `${STORE_PATH}.tmp`
  await fs.writeFile(tempPath, JSON.stringify(store, null, 2), 'utf-8')
  await fs.rename(tempPath, STORE_PATH)
}

export async function readJournalStore() {
  try {
    const text = await fs.readFile(STORE_PATH, 'utf-8')
    const parsed = JSON.parse(text)
    return {
      profiles: parsed?.profiles && typeof parsed.profiles === 'object' ? parsed.profiles : {},
      trades: Array.isArray(parsed?.trades) ? parsed.trades : [],
      reviews: Array.isArray(parsed?.reviews) ? parsed.reviews : [],
    }
  } catch {
    const initialStore = cloneDefaultStore()
    await writeStore(initialStore)
    return initialStore
  }
}

export async function updateJournalStore(mutator) {
  const currentStore = await readJournalStore()
  const workingCopy = JSON.parse(JSON.stringify(currentStore))
  const nextStore = (await mutator(workingCopy)) ?? workingCopy
  await writeStore(nextStore)
  return nextStore
}
