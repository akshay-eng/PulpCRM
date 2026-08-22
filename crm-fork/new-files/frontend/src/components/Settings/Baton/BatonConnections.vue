<template>
  <SettingsLayoutBase
    :title="__('AI models')"
    :description="__('The models Baton thinks with. Bots and workflows pick from these — they never hold a key themselves.')"
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
                ? __('On. Bots and workflows may call a model, and may message customers as far as the sending mode allows.')
                : __('Off. Nothing calls a model and nothing reaches a customer. You can still test credentials.') }}
            </div>
          </div>
          <Switch :model-value="Boolean(data.ai_enabled)" @update:model-value="setAiEnabled" />
        </div>

        <!--
          Sending mode sits with the switch rather than with the channel: it is
          about what the AI is allowed to do, not about which bridge carries it.
        -->
        <div v-if="data.ai_enabled"
          class="mt-3 flex flex-wrap items-center gap-3 border-t border-outline-gray-1 pt-3">
          <span class="text-p-sm text-ink-gray-7">{{ __('Outgoing messages') }}</span>
          <div class="flex gap-1">
            <button
              v-for="m in ['Auto', 'Draft', 'Off']"
              :key="m"
              class="rounded-md px-2.5 py-1 text-p-sm transition"
              :class="data.whatsapp_send_mode === m
                ? 'bg-surface-gray-3 font-medium text-ink-gray-9'
                : 'text-ink-gray-6 hover:bg-surface-gray-2'"
              @click="setMode(m)"
            >{{ m }}</button>
          </div>
          <span class="text-p-sm text-ink-gray-5">
            {{ __('Draft asks a human to approve before anything sends.') }}
          </span>
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

      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup>
/**
 * AI model credentials, and the master switch everything sits behind.
 *
 * WhatsApp lives in CRM's own WhatsApp settings tab, not here. It used to be
 * on this page too, which meant two places configured one channel -- and the
 * CRM already had a tab for it.
 */
import SettingsLayoutBase from '@/components/Layouts/SettingsLayoutBase.vue'
import { Badge, Button, FormControl, Select, Switch, call, toast } from 'frappe-ui'
import { ref, onMounted } from 'vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSparkles from '~icons/lucide/sparkles'
import LucideCheckCircle from '~icons/lucide/check-circle'
import LucidePowerOff from '~icons/lucide/power-off'

const PROVIDERS = ['OpenAI Compatible', 'Anthropic', 'Google Gemini', 'Ollama', 'Azure OpenAI']
const PURPOSES = ['General', 'Qualification', 'Conversation', 'Summarisation', 'Workflow']

const data = ref({})
const models = ref([])
const loading = ref(false)
const editing = ref(null)
const draftKey = ref('')
const savingModel = ref(false)
const testingModel = ref(false)
const modelResult = ref({})

async function load() {
  loading.value = true
  try {
    models.value = await call('baton.api.connections.get_models')
    data.value = await call('baton.api.connections.get_connections')
  } finally {
    loading.value = false
  }
}

async function setAiEnabled(on) {
  try {
    data.value = await call('baton.api.connections.set_ai_enabled', { enabled: on ? 1 : 0 })
    toast.success(on ? __('AI automation is on') : __('AI automation is off'))
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not change it'))
  }
}

async function setMode(mode) {
  data.value = await call('baton.api.connections.set_send_mode', { mode })
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

onMounted(load)
</script>
