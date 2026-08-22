<template>
  <Dialog
    v-model="show"
    :options="{ title: __('Connect OpenWA'), size: 'xl' }"
  >
    <template #body-content>
      <p class="mb-4 text-p-sm text-ink-gray-6">
        {{ __('OpenWA is a self-hosted bridge that runs on your own WhatsApp account. It has no 24-hour window and needs no approved templates, and unlike the official API it can see replies you type on your own phone — which is what lets automation pause itself when you step in. It is unofficial and carries account-ban risk.') }}
      </p>

      <div class="grid grid-cols-2 gap-4">
        <FormControl
          v-model="form.base_url"
          type="text"
          :label="__('Server URL')"
          placeholder="http://localhost:2785"
          :description="__('Where your OpenWA instance is reachable.')"
        />
        <FormControl
          v-model="form.api_key"
          type="password"
          :label="stored.has_api_key ? __('API key (stored — blank keeps it)') : __('API key')"
          placeholder="owa_…"
          :description="__('Found in your OpenWA dashboard, or data/.api-key.')"
        />
      </div>

      <div class="mt-4">
        <div class="mb-1 text-xs text-ink-gray-6">{{ __('Session') }}</div>
        <div class="flex gap-2">
          <select
            v-model="form.session_id"
            class="flex-1 rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5 text-base text-ink-gray-8"
          >
            <option value="">{{ __('— fetch, then choose —') }}</option>
            <option v-for="s in sessionOptions" :key="s.id" :value="s.id">
              {{ s.name }}{{ s.status ? ' — ' + s.status : '' }}{{ s.phone ? ' · +' + s.phone : '' }}
            </option>
          </select>
          <Button :label="__('Fetch')" :loading="fetching" @click="fetchSessions" />
        </div>
        <div v-if="sessionError" class="mt-1 text-xs text-red-600">{{ sessionError }}</div>
        <div v-else class="mt-1 text-xs text-ink-gray-5">
          {{ __('The session must be logged in (status “ready”) before Baton can send.') }}
        </div>
      </div>

      <div
        v-if="result"
        class="mt-4 rounded-md px-3 py-2 text-xs"
        :class="result.ok ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-700'"
      >
        {{ result.msg }}
      </div>
    </template>

    <template #actions>
      <div class="flex justify-between gap-2">
        <Button :label="__('Test connection')" :loading="testing" @click="test" />
        <div class="flex gap-2">
          <Button :label="__('Cancel')" @click="show = false" />
          <Button
            variant="solid"
            :label="__('Connect')"
            :loading="saving"
            :disabled="!form.session_id"
            @click="connect"
          />
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Dialog, Button, FormControl, call, toast } from 'frappe-ui'
import { ref, reactive, computed, watch } from 'vue'

const show = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['connected'])

const form = reactive({ base_url: 'http://localhost:2785', api_key: '', session_id: '' })
const stored = ref({})
const sessions = ref([])
const fetching = ref(false)
const testing = ref(false)
const saving = ref(false)
const sessionError = ref('')
const result = ref(null)

const sessionOptions = computed(() => {
  const list = [...sessions.value]
  const s = stored.value.session_id
  if (s && !list.some((x) => x.id === s)) {
    list.unshift({ id: s, name: __('Saved session'), status: '', phone: '' })
  }
  return list
})

async function load() {
  const c = await call('baton.api.connections.get_connections')
  stored.value = c.openwa || {}
  form.base_url = stored.value.base_url || 'http://localhost:2785'
  form.session_id = stored.value.session_id || ''
  form.api_key = ''
  result.value = null
  sessionError.value = ''
}

async function fetchSessions() {
  fetching.value = true
  sessionError.value = ''
  try {
    const r = await call('baton.api.connections.list_openwa_sessions', {
      base_url: form.base_url,
      api_key: form.api_key || undefined,
    })
    if (!r.ok) {
      sessions.value = []
      sessionError.value = r.error
      return
    }
    sessions.value = r.sessions
    if (!form.session_id && r.sessions.length === 1) form.session_id = r.sessions[0].id
  } finally {
    fetching.value = false
  }
}

async function test() {
  testing.value = true
  try {
    // Save first: the backend tests what is configured, not what is typed.
    await call('baton.api.connections.save_openwa', {
      base_url: form.base_url,
      api_key: form.api_key || undefined,
      session_id: form.session_id,
    })
    const r = await call('baton.api.connections.test_openwa')
    result.value = r.ok
      ? { ok: true, msg: __('Connected — session “{0}” is {1}.', [r.name || '', r.status]) }
      : { ok: false, msg: r.error || __('Could not reach OpenWA.') }
  } finally {
    testing.value = false
  }
}

async function connect() {
  saving.value = true
  try {
    await call('baton.api.connections.save_openwa', {
      base_url: form.base_url,
      api_key: form.api_key || undefined,
      session_id: form.session_id,
    })
    await call('baton.api.connections.set_active_channel', { channel: 'openwa' })

    // Register the inbound webhook, so replies actually reach the CRM. Without
    // it sending works and nothing ever comes back, which looks like success.
    try {
      const s = await call('baton.api.connections.suggest_webhook_url')
      await call('baton.api.connections.register_openwa_webhook', { public_url: s.url })
      toast.success(__('OpenWA connected and webhook registered'))
    } catch (e) {
      toast.warning(__('Connected, but the webhook could not be registered: {0}', [e.message || e]))
    }

    form.api_key = ''
    show.value = false
    emit('connected')
  } finally {
    saving.value = false
  }
}

watch(show, (v) => v && load())
</script>
