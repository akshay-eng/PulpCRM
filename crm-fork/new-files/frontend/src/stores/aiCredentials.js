import { computed, reactive } from 'vue'

const STORAGE_VERSION = 1
const STORAGE_PREFIX = 'pulp.ai-credentials'

const state = reactive({
  credentials: [],
  selections: {},
})

let loadedFrom = null

function currentUser() {
  return window.frappe?.session?.user || 'local'
}

function storageKey() {
  return `${STORAGE_PREFIX}.v${STORAGE_VERSION}.${currentUser()}`
}

function load() {
  const key = storageKey()
  if (loadedFrom === key) return

  loadedFrom = key
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}')
    state.credentials = Array.isArray(saved.credentials)
      ? saved.credentials.filter((item) => item?.id && item?.model_name)
      : []
    state.selections = saved.selections || {}
  } catch {
    state.credentials = []
    state.selections = {}
  }
}

function persist() {
  load()
  localStorage.setItem(
    storageKey(),
    JSON.stringify({
      version: STORAGE_VERSION,
      credentials: state.credentials,
      selections: state.selections,
    }),
  )
}

function normalizedCredential(value) {
  const modelName = String(value.model_name || value.id || '').trim()
  return {
    id: modelName,
    model_name: modelName,
    label: String(value.label || modelName).trim(),
    provider: value.provider || 'OpenAI Compatible',
    model: String(value.model || '').trim(),
    base_url: String(value.base_url || '').trim(),
    api_version: String(value.api_version || '').trim(),
    api_key: String(value.api_key || ''),
    updated_at: new Date().toISOString(),
  }
}

export function useAICredentials() {
  load()

  const credentials = computed(() => {
    load()
    return state.credentials
  })

  const options = computed(() =>
    credentials.value.map((item) => ({
      label: `${item.label} · ${item.provider}`,
      value: item.id,
    })),
  )

  function getCredential(id) {
    load()
    return state.credentials.find((item) => item.id === id) || null
  }

  function saveCredential(value) {
    const credential = normalizedCredential(value)
    if (!credential.id) throw new Error('A model name is required')

    const index = state.credentials.findIndex(
      (item) => item.id === credential.id,
    )
    if (index === -1) state.credentials.unshift(credential)
    else state.credentials[index] = credential
    persist()
    return credential
  }

  function removeCredential(id) {
    state.credentials = state.credentials.filter((item) => item.id !== id)
    for (const [context, selected] of Object.entries(state.selections)) {
      if (selected === id) delete state.selections[context]
    }
    persist()
  }

  function isReady(id) {
    const credential = getCredential(id)
    return Boolean(
      credential &&
      (credential.provider === 'Ollama' || credential.api_key.trim()),
    )
  }

  function getSelection(context, fallback = '') {
    load()
    const selected = state.selections[context]
    if (selected && getCredential(selected)) return selected
    if (fallback && getCredential(fallback)) return fallback
    return credentials.value[0]?.id || ''
  }

  function setSelection(context, id) {
    if (id) state.selections[context] = id
    else delete state.selections[context]
    persist()
  }

  function requestCredential(id) {
    const credential = getCredential(id)
    if (!credential) return undefined
    return JSON.stringify({
      model_name: credential.model_name,
      api_key: credential.api_key,
    })
  }

  return {
    credentials,
    options,
    getCredential,
    saveCredential,
    removeCredential,
    isReady,
    getSelection,
    setSelection,
    requestCredential,
  }
}
