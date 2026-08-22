<template>
  <SettingsLayoutBase
    :title="__('Models & channels')"
    :description="__('Credentials Baton uses to reach the outside world. Bots and workflows pick from these — they never hold a key themselves.')"
  >
    <template #header-actions>
      <Button :label="__('Refresh')" :loading="loading" @click="load">
        <template #prefix><LucideRefreshCw class="h-4 w-4" /></template>
      </Button>
    </template>

    <template #content>
      <div>
      <!--
        The master switch. It had no UI anywhere, so the only way to turn Baton
        on was Desk -- which meant this page could not finish configuring the
        product it configures.
      -->
      <div class="mb-5 rounded-lg border px-4 py-3"
        :class="data.ai_enabled
          ? 'border-outline-gray-2 bg-surface-white'
          : 'border-amber-200 bg-amber-50'">
        <div class="flex items-center gap-3">
          <component :is="data.ai_enabled ? LucideCheckCircle : LucidePowerOff"
            class="h-5 w-5 shrink-0"
            :class="data.ai_enabled ? 'text-green-600' : 'text-amber-600'" />
          <div class="min-w-0 flex-1">
            <div class="text-p-base font-medium text-ink-gray-8">
              {{ __('AI automation') }}
            </div>
            <div class="text-p-sm" :class="data.ai_enabled ? 'text-ink-gray-5' : 'text-amber-700'">
              {{ data.ai_enabled
                ? __('On. Bots and workflows may call a model and message customers, subject to the sending mode below.')
                : __('Off. Nothing calls a model and nothing reaches a customer. You can still test credentials.') }}
            </div>
          </div>
          <Switch :model-value="Boolean(data.ai_enabled)" @update:model-value="setAiEnabled" />
        </div>
      </div>

      <!-- AI models: the credential a bot points at. -->
      <div class="mb-5 rounded-lg border border-outline-gray-2 bg-surface-white">
        <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3">
          <div class="flex items-center gap-2">
            <LucideSparkles class="h-4 w-4 text-ink-gray-7" />
            <span class="text-p-base font-medium text-ink-gray-8">{{ __('AI models') }}</span>
          </div>
          <Button :label="__('Add a model')" @click="newModel" />
        </div>

        <div v-if="!models.length" class="px-4 py-5 text-center text-p-base text-ink-gray-5">
          {{ __('No model configured, so nothing that needs the AI can run.') }}
        </div>

        <div v-for="m in models" :key="m.model_name"
          class="border-b border-outline-gray-1 px-4 py-3 last:border-0">
          <div class="flex items-center gap-2">
            <span class="text-p-base font-medium text-ink-gray-8">{{ m.model_name }}</span>
            <Badge v-if="m.is_default" theme="green" variant="subtle">{{ __('Default') }}</Badge>
            <Badge :theme="m.has_api_key ? 'gray' : 'orange'" variant="subtle">
              {{ m.has_api_key ? m.provider : __('No key') }}
            </Badge>
            <span v-if="modelResult[m.model_name] && editing !== m.model_name"
              class="ml-auto text-p-sm"
              :class="modelResult[m.model_name].ok ? 'text-green-700' : 'text-red-600'">
              {{ modelResult[m.model_name].msg }}
            </span>
            <span v-else class="ml-auto text-p-sm text-ink-gray-5">{{ m.model }}</span>
            <!-- the open editor shows its own result next to the buttons -->
            <Button variant="ghost" :label="editing === m.model_name ? __('Close') : __('Edit')"
              @click="editing = editing === m.model_name ? null : m.model_name" />
          </div>

          <div v-if="editing === m.model_name" class="mt-3 grid grid-cols-2 gap-3">
            <div>
              <div class="mb-1 text-p-sm text-ink-gray-7">{{ __('Provider') }}</div>
              <Select v-model="m.provider" :options="PROVIDERS" />
            </div>
            <FormControl v-model="m.model" type="text" :label="__('Model')"
              placeholder="claude-sonnet-4-5" />
            <FormControl v-model="m.base_url" type="text" :label="__('Base URL')"
              :description="__('Blank uses the provider default.')" />
            <FormControl v-model="draftKey" type="password"
              :label="m.has_api_key ? __('API key (stored - blank keeps it)') : __('API key')" />
            <div>
              <div class="mb-1 text-p-sm text-ink-gray-7">{{ __('Used for') }}</div>
              <Select v-model="m.purpose" :options="PURPOSES" />
            </div>
            <div class="flex items-end gap-2">
              <Button variant="solid" :label="__('Save')" :loading="savingModel"
                @click="saveModel(m)" />
              <Button :label="__('Test')" :loading="testingModel" @click="testModel(m)" />
              <Button theme="red" variant="ghost" :label="__('Delete')" @click="removeModel(m)" />
            </div>
            <div class="col-span-2 flex items-center gap-2">
              <input :id="'def-' + m.model_name" v-model="m.is_default" type="checkbox" />
              <label :for="'def-' + m.model_name" class="text-p-sm text-ink-gray-7">
                {{ __('Use this when nothing more specific is set') }}
              </label>
              <span v-if="modelResult[m.model_name] && editing !== m.model_name"
              class="ml-auto text-p-sm"
                :class="modelResult[m.model_name].ok ? 'text-green-700' : 'text-red-600'">
                {{ modelResult[m.model_name].msg }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- which channel is live -->
      <div class="mb-5 rounded-lg border border-outline-gray-2 bg-surface-white p-4">
        <div class="mb-1 text-base font-medium text-ink-gray-8">{{ __('WhatsApp channel') }}</div>
        <div class="mb-3 text-sm text-ink-gray-5">
          {{ __('Which bridge Baton sends through. Only one is active at a time.') }}
        </div>
        <div class="flex gap-3">
          <button
            v-for="opt in channels"
            :key="opt.id"
            class="flex-1 rounded-lg border px-4 py-3 text-left transition"
            :class="data.active_channel === opt.id
              ? 'border-orange-400 bg-orange-50 ring-1 ring-orange-200'
              : 'border-outline-gray-2 hover:border-outline-gray-3'"
            @click="switchChannel(opt.id)"
          >
            <div class="flex items-center gap-2">
              <component :is="opt.icon" class="h-4 w-4 text-ink-gray-7" />
              <span class="text-sm font-medium text-ink-gray-8">{{ opt.label }}</span>
              <Badge v-if="data.active_channel === opt.id" theme="orange" variant="subtle">
                {{ __('Active') }}
              </Badge>
            </div>
            <div class="mt-1 text-xs text-ink-gray-5">{{ opt.blurb }}</div>
          </button>
        </div>

        <div class="mt-4 flex items-center gap-3 border-t border-outline-gray-1 pt-3">
          <span class="text-sm text-ink-gray-7">{{ __('Sending mode') }}</span>
          <div class="flex gap-1">
            <button
              v-for="m in ['Auto', 'Draft', 'Off']"
              :key="m"
              class="rounded-md px-2.5 py-1 text-xs transition"
              :class="data.whatsapp_send_mode === m
                ? 'bg-surface-gray-3 font-medium text-ink-gray-9'
                : 'text-ink-gray-6 hover:bg-surface-gray-2'"
              @click="setMode(m)"
            >{{ m }}</button>
          </div>
          <span class="text-xs text-ink-gray-5">
            {{ __('Draft asks a human to approve before anything sends.') }}
          </span>
        </div>
      </div>

      <!-- OpenWA -->
      <div class="mb-5 rounded-lg border border-outline-gray-2 bg-surface-white">
        <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3">
          <div class="flex items-center gap-2">
            <LucideServer class="h-4 w-4 text-ink-gray-7" />
            <span class="text-base font-medium text-ink-gray-8">{{ __('OpenWA') }}</span>
            <span class="text-xs text-ink-gray-5">{{ __('self-hosted · unofficial') }}</span>
          </div>
          <Badge :theme="openwaStatus.theme" variant="subtle">{{ openwaStatus.label }}</Badge>
        </div>

        <div class="grid grid-cols-2 gap-4 px-4 py-4">
          <FormControl v-model="wa.base_url" type="text" :label="__('Server URL')"
                       placeholder="http://localhost:2785" />
          <FormControl v-model="wa.api_key" type="password"
                       :label="data.openwa?.has_api_key ? __('API key (stored — leave blank to keep)') : __('API key')"
                       placeholder="owa_…" />
          <div class="col-span-2">
            <div class="mb-1 text-xs text-ink-gray-6">{{ __('Session') }}</div>
            <div class="flex gap-2">
              <select v-model="wa.session_id"
                      class="flex-1 rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5 text-sm text-ink-gray-8">
                <option value="">{{ __('— select a session —') }}</option>
                <option v-for="s in sessionOptions" :key="s.id" :value="s.id">
                  {{ s.name }}{{ s.status ? ' — ' + s.status : '' }}{{ s.phone ? ' · +' + s.phone : '' }}
                </option>
              </select>
              <Button :label="__('Fetch sessions')" :loading="fetching" @click="fetchSessions" />
            </div>
            <div v-if="sessionError" class="mt-1 text-xs text-red-600">{{ sessionError }}</div>
          </div>
        </div>

        <div class="flex items-center gap-2 border-t border-outline-gray-2 px-4 py-3">
          <Button variant="solid" :label="__('Save')" :loading="saving" @click="saveOpenwa" />
          <Button :label="__('Test connection')" :loading="testing" @click="testOpenwa" />
          <Button :label="__('Register webhook')" :loading="hooking" @click="registerHook" />
          <span v-if="testResult" class="text-xs" :class="testResult.ok ? 'text-green-700' : 'text-red-600'">
            {{ testResult.msg }}
          </span>
        </div>
        <div v-if="webhookNote" class="border-t border-outline-gray-1 px-4 py-2 text-xs text-ink-gray-5">
          {{ webhookNote }}
        </div>
      </div>

      <!-- Meta -->
      <div class="rounded-lg border border-outline-gray-2 bg-surface-white">
        <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3">
          <div class="flex items-center gap-2">
            <LucideBadgeCheck class="h-4 w-4 text-ink-gray-7" />
            <span class="text-base font-medium text-ink-gray-8">{{ __('Meta Cloud API') }}</span>
            <span class="text-xs text-ink-gray-5">{{ __('official') }}</span>
          </div>
          <Badge :theme="data.meta?.active ? 'green' : 'gray'" variant="subtle">
            {{ data.meta?.active ? __('Active') : __('Not active') }}
          </Badge>
        </div>

        <div v-if="!data.meta?.installed" class="px-4 py-4 text-sm text-ink-gray-6">
          {{ __('The frappe_whatsapp app is not installed, so the official channel is unavailable.') }}
        </div>

        <template v-else>
          <div class="grid grid-cols-2 gap-4 px-4 py-4">
            <FormControl v-model="meta.phone_id" type="text" :label="__('Phone number ID')" />
            <FormControl v-model="meta.business_id" type="text" :label="__('WhatsApp Business Account ID')" />
            <FormControl v-model="meta.app_id" type="text" :label="__('App ID')" />
            <FormControl v-model="meta.token" type="password"
                         :label="metaAccount?.has_token ? __('Access token (stored — blank keeps it)') : __('Access token')"
                         placeholder="EAA…" />
            <FormControl v-model="meta.app_secret" type="password"
                         :label="data.meta?.has_app_secret ? __('App secret (stored — blank keeps it)') : __('App secret')" />
            <div class="flex items-end">
              <div class="text-xs text-ink-gray-5">
                {{ __('The app secret verifies inbound webhook signatures. Without it Baton refuses the webhook.') }}
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2 border-t border-outline-gray-2 px-4 py-3">
            <Button variant="solid" :label="__('Save')" :loading="savingMeta" @click="saveMeta" />
            <Button :label="__('Test connection')" :loading="testingMeta" @click="testMeta" />
            <Button :label="metaAccount?.status === 'Active' ? __('Deactivate') : __('Activate')"
                    @click="toggleMeta" />
            <span v-if="metaResult" class="text-xs" :class="metaResult.ok ? 'text-green-700' : 'text-red-600'">
              {{ metaResult.msg }}
            </span>
          </div>
        </template>
      </div>

      <div class="mt-4 rounded-md bg-surface-gray-2 px-4 py-3 text-p-sm text-ink-gray-6">
        <b>{{ __('Which should you use?') }}</b>
        {{ __('Meta is official and durable, but cannot see messages you type on your own phone — so human-handoff detection is partial. OpenWA rides your real account and sees everything, which makes handoff exact, but it is unofficial and carries account-ban risk.') }}
      </div>
      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup>
import SettingsLayoutBase from '@/components/Layouts/SettingsLayoutBase.vue'
import { Button, Badge, FormControl, Select, Switch, call, toast } from 'frappe-ui'
import { ref, reactive, computed, onMounted } from 'vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideServer from '~icons/lucide/server'
import LucideBadgeCheck from '~icons/lucide/badge-check'
import LucideSparkles from '~icons/lucide/sparkles'
import LucideCheckCircle from '~icons/lucide/check-circle'
import LucidePowerOff from '~icons/lucide/power-off'


const PROVIDERS = ['OpenAI Compatible', 'Anthropic', 'Google Gemini', 'Ollama', 'Azure OpenAI']
const PURPOSES = ['General', 'Qualification', 'Conversation', 'Summarisation', 'Workflow']

const models = ref([])
const editing = ref(null)
const draftKey = ref('')
const savingModel = ref(false)
const testingModel = ref(false)
const modelResult = ref({})

async function setAiEnabled(on) {
  try {
    data.value = await call('baton.api.connections.set_ai_enabled', { enabled: on ? 1 : 0 })
    toast.success(on ? __('AI automation is on') : __('AI automation is off'))
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not change it'))
  }
}

async function loadModels() {
  models.value = await call('baton.api.connections.get_models')
}

function newModel() {
  const name = __('New model {0}', [models.value.length + 1])
  models.value.unshift({
    model_name: name, provider: 'Anthropic', model: '', purpose: 'General',
    enabled: 1, is_default: models.value.length === 0, has_api_key: false, unsaved: true,
  })
  editing.value = name
  draftKey.value = ''
}

async function saveModel(m) {
  savingModel.value = true
  try {
    models.value = await call('baton.api.connections.save_model', {
      model_name: m.model_name,
      new_name: m.unsaved ? m.model_name : undefined,
      api_key: draftKey.value || undefined,
      provider: m.provider, model: m.model, base_url: m.base_url,
      purpose: m.purpose, is_default: m.is_default ? 1 : 0, enabled: 1,
    })
    draftKey.value = ''  // never keep a secret in the page after saving
    editing.value = null
    toast.success(__('Saved'))
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not save the model'))
  } finally {
    savingModel.value = false
  }
}

async function testModel(m) {
  testingModel.value = true
  try {
    const r = await call('baton.api.connections.test_model', { model_name: m.model_name })
    modelResult.value = {
      ...modelResult.value,
      [m.model_name]: {
        ok: r.ok,
        msg: r.ok ? __('Replied in {0}ms', [r.latency_ms]) : r.error || r.message,
      },
    }
  } finally {
    testingModel.value = false
  }
}

async function removeModel(m) {
  if (m.unsaved) {
    models.value = models.value.filter((x) => x !== m)
    return
  }
  if (!window.confirm(__('Delete this model?'))) return
  models.value = await call('baton.api.connections.delete_model', { model_name: m.model_name })
}

const data = ref({})
const sessions = ref([])
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const hooking = ref(false)
const fetching = ref(false)
const savingMeta = ref(false)
const testingMeta = ref(false)
const testResult = ref(null)
const metaResult = ref(null)
const sessionError = ref('')
const webhookNote = ref('')

const wa = reactive({ base_url: '', api_key: '', session_id: '' })
const meta = reactive({ phone_id: '', business_id: '', app_id: '', token: '', app_secret: '' })

const channels = [
  { id: 'openwa', label: 'OpenWA', icon: LucideServer,
    blurb: 'Self-hosted bridge on your own account. Sees your manual replies.' },
  { id: 'meta', label: 'Meta Cloud API', icon: LucideBadgeCheck,
    blurb: 'Official API. Templates and a 24-hour window apply.' },
]

const metaAccount = computed(() => (data.value.meta?.accounts || [])[0])

// Always include the stored session, so a configured connector does not render
// as unconfigured before the user clicks Fetch.
const sessionOptions = computed(() => {
  const list = [...sessions.value]
  const stored = data.value.openwa?.session_id
  if (stored && !list.some((s) => s.id === stored)) {
    list.unshift({ id: stored, name: __('Saved session'), status: '', phone: '' })
  }
  return list
})

const openwaStatus = computed(() => {
  const o = data.value.openwa || {}
  if (!o.has_api_key) return { theme: 'gray', label: __('Not configured') }
  if (!o.session_id) return { theme: 'orange', label: __('No session') }
  if (!o.has_webhook_secret) return { theme: 'orange', label: __('No webhook') }
  return { theme: 'green', label: __('Configured') }
})

async function load() {
  loading.value = true
  try {
    await loadModels()
    data.value = await call('baton.api.connections.get_connections')
    wa.base_url = data.value.openwa?.base_url || ''
    wa.session_id = data.value.openwa?.session_id || ''
    const m = metaAccount.value
    if (m) {
      meta.phone_id = m.phone_id || ''
      meta.business_id = m.business_id || ''
      meta.app_id = m.app_id || ''
    }
  } finally {
    loading.value = false
  }
}

async function switchChannel(id) {
  data.value = await call('baton.api.connections.set_active_channel', { channel: id })
  toast.success(__('WhatsApp now goes through {0}', [id === 'openwa' ? 'OpenWA' : 'Meta']))
}

async function setMode(mode) {
  data.value = await call('baton.api.connections.set_send_mode', { mode })
}

async function fetchSessions() {
  fetching.value = true
  sessionError.value = ''
  try {
    const r = await call('baton.api.connections.list_openwa_sessions', {
      base_url: wa.base_url, api_key: wa.api_key || undefined,
    })
    if (!r.ok) { sessionError.value = r.error; sessions.value = []; return }
    sessions.value = r.sessions
    if (!wa.session_id && r.sessions.length === 1) wa.session_id = r.sessions[0].id
  } finally {
    fetching.value = false
  }
}

async function saveOpenwa() {
  saving.value = true
  try {
    data.value = await call('baton.api.connections.save_openwa', {
      base_url: wa.base_url, api_key: wa.api_key || undefined, session_id: wa.session_id,
    })
    wa.api_key = ''  // never keep a secret in the page after saving
    toast.success(__('Saved'))
  } finally {
    saving.value = false
  }
}

async function testOpenwa() {
  testing.value = true
  try {
    const r = await call('baton.api.connections.test_openwa')
    testResult.value = r.ok
      ? { ok: true, msg: __('Session {0} — {1}', [r.name || '', r.status]) }
      : { ok: false, msg: r.error || __('Failed') }
  } finally {
    testing.value = false
  }
}

async function registerHook() {
  hooking.value = true
  try {
    const s = await call('baton.api.connections.suggest_webhook_url')
    const r = await call('baton.api.connections.register_openwa_webhook', { public_url: s.url })
    webhookNote.value = __('Webhook registered at {0} — {1}', [r.url, s.note])
    toast.success(__('Webhook registered'))
    await load()
  } catch (e) {
    webhookNote.value = e.message || String(e)
  } finally {
    hooking.value = false
  }
}

async function saveMeta() {
  savingMeta.value = true
  try {
    data.value = await call('baton.api.connections.save_meta', {
      account: metaAccount.value?.name,
      phone_id: meta.phone_id, business_id: meta.business_id, app_id: meta.app_id,
      token: meta.token || undefined, app_secret: meta.app_secret || undefined,
    })
    meta.token = ''
    meta.app_secret = ''
    toast.success(__('Saved'))
  } finally {
    savingMeta.value = false
  }
}

async function testMeta() {
  testingMeta.value = true
  try {
    const r = await call('baton.api.connections.test_meta', { account: metaAccount.value?.name })
    metaResult.value = r.ok
      ? { ok: true, msg: __('{0} ({1})', [r.display_name || '', r.number || '']) }
      : { ok: false, msg: r.error }
  } finally {
    testingMeta.value = false
  }
}

async function toggleMeta() {
  const next = metaAccount.value?.status === 'Active' ? 'Inactive' : 'Active'
  data.value = await call('baton.api.connections.save_meta', {
    account: metaAccount.value?.name, status: next,
  })
  toast.success(__('Account {0}', [next]))
}

onMounted(load)
</script>
