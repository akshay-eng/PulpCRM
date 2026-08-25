import { beforeEach, describe, expect, it, vi } from 'vitest'

async function vaultFor(user) {
  window.frappe = { session: { user } }
  vi.resetModules()
  const { useAICredentials } = await import('@/stores/aiCredentials')
  return useAICredentials()
}

describe('browser AI credential vault', () => {
  beforeEach(() => localStorage.clear())

  it('shares one credential across contexts for the same user', async () => {
    const vault = await vaultFor('one@example.com')
    vault.saveCredential({
      model_name: 'Primary Gemini',
      provider: 'Google Gemini',
      model: 'gemini-test',
      api_key: 'browser-secret',
    })
    vault.setSelection('ask', 'Primary Gemini')

    expect(vault.getSelection('ask')).toBe('Primary Gemini')
    expect(vault.getSelection('workflow:demo')).toBe('Primary Gemini')
    expect(vault.getCredential('Primary Gemini').api_key).toBe('browser-secret')
  })

  it('sends only the model identity and transient key', async () => {
    const vault = await vaultFor('two@example.com')
    vault.saveCredential({
      model_name: 'Local key',
      provider: 'OpenAI Compatible',
      model: 'private-model',
      base_url: 'https://example.test/v1',
      api_key: 'browser-secret',
    })

    expect(JSON.parse(vault.requestCredential('Local key'))).toEqual({
      model_name: 'Local key',
      api_key: 'browser-secret',
    })
  })

  it('keeps credentials separate for different signed-in users', async () => {
    const first = await vaultFor('first@example.com')
    first.saveCredential({
      model_name: 'First user model',
      api_key: 'first-secret',
    })

    const second = await vaultFor('second@example.com')
    expect(second.credentials.value).toEqual([])
  })
})
