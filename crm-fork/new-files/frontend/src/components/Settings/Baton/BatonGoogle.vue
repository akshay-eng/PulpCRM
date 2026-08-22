<template>
  <SettingsLayoutBase
    :title="__('Google')"
    :description="__('Sign in with Google, and send email from your own Gmail rather than a shared mailbox.')"
  >
    <template #header-actions>
      <Button :label="__('Refresh')" :loading="loading" @click="load">
        <template #prefix><LucideRefreshCw class="h-4 w-4" /></template>
      </Button>
    </template>

    <template #content>
      <div>
        <!-- 1. the credentials -->
        <div class="mb-5 rounded-lg border border-outline-gray-2 bg-surface-white">
          <div class="flex items-center gap-2 border-b border-outline-gray-2 px-4 py-3">
            <LucideKeyRound class="h-4 w-4 text-ink-gray-7" />
            <span class="text-p-base font-medium text-ink-gray-8">
              {{ __('Google Cloud client') }}
            </span>
            <Badge class="ml-auto" :theme="data.has_client_secret ? 'green' : 'gray'"
              variant="subtle">
              {{ data.has_client_secret ? __('Configured') : __('Not configured') }}
            </Badge>
          </div>

          <div class="grid grid-cols-2 gap-4 px-4 py-4">
            <FormControl v-model="form.client_id" type="text" :label="__('Client ID')"
              placeholder="…apps.googleusercontent.com" />
            <FormControl v-model="form.client_secret" type="password"
              :label="data.has_client_secret
                ? __('Client secret (stored — blank keeps it)') : __('Client secret')" />
          </div>

          <!--
            Both callbacks, together. Sign-in and mail are separate OAuth flows
            in Frappe with separate callbacks, and configuring one of the two
            fails later with a redirect_uri_mismatch that says nothing useful.
          -->
          <div class="border-t border-outline-gray-1 px-4 py-3">
            <div class="mb-2 text-p-sm text-ink-gray-6">
              {{ __('Paste these into your Google Cloud OAuth client, under “Authorised redirect URIs”. Both are needed.') }}
            </div>
            <div v-for="(uri, key) in redirects" :key="key"
              class="mb-1.5 flex items-center gap-2">
              <span class="w-16 shrink-0 text-p-sm text-ink-gray-5">{{ key }}</span>
              <!--
                The mail callback is composed by Frappe and carries the OAuth
                client's document name, so it does not exist until Save has
                created it. Showing a guess here would be subtly wrong and fail
                only at the consent screen.
              -->
              <code v-if="uri"
                class="flex-1 truncate rounded bg-surface-gray-2 px-2 py-1 text-xs text-ink-gray-7">
                {{ uri }}
              </code>
              <span v-else class="flex-1 text-p-sm text-ink-gray-5">
                {{ __('Appears once you save — it carries a generated id.') }}
              </span>
              <Button v-if="uri" variant="ghost"
                :label="copied === key ? __('Copied') : __('Copy')"
                @click="copy(key, uri)" />
            </div>
            <div class="mt-1 flex items-center gap-2">
              <span class="w-16 shrink-0 text-p-sm text-ink-gray-5">{{ __('origin') }}</span>
              <code class="flex-1 truncate rounded bg-surface-gray-2 px-2 py-1 text-xs text-ink-gray-7">
                {{ data.redirect_uris?.origin }}
              </code>
              <Button variant="ghost"
                :label="copied === 'origin' ? __('Copied') : __('Copy')"
                @click="copy('origin', data.redirect_uris?.origin)" />
            </div>
          </div>

          <div class="flex items-center gap-3 border-t border-outline-gray-2 px-4 py-3">
            <Button variant="solid" :label="__('Save')" :loading="saving" @click="save" />
            <div class="flex items-center gap-2">
              <Switch :model-value="Boolean(form.enable_login)"
                @update:model-value="form.enable_login = $event" />
              <span class="text-p-sm text-ink-gray-7">{{ __('Show “Sign in with Google”') }}</span>
            </div>
            <span class="ml-auto text-p-sm text-ink-gray-5">
              {{ __('New accounts are denied by default — invite people first.') }}
            </span>
          </div>
        </div>

        <!-- 2. your own mailbox -->
        <div class="rounded-lg border border-outline-gray-2 bg-surface-white">
          <div class="flex items-center gap-2 border-b border-outline-gray-2 px-4 py-3">
            <LucideMail class="h-4 w-4 text-ink-gray-7" />
            <span class="text-p-base font-medium text-ink-gray-8">
              {{ __('Send email as yourself') }}
            </span>
            <Badge class="ml-auto" :theme="mine.ready ? 'green' : 'gray'" variant="subtle">
              {{ mine.ready ? __('Connected') : __('Not connected') }}
            </Badge>
          </div>

          <div v-if="!data.has_client_secret" class="px-4 py-4 text-p-base text-ink-gray-6">
            {{ __('Add the Google Cloud client above first.') }}
          </div>

          <template v-else>
            <div class="px-4 py-4">
              <div class="mb-3 text-p-sm text-ink-gray-6">
                {{ __('Connecting sends CRM email out of your own mailbox, so replies come back to you and the thread lives in your Sent folder. Bots can be pointed at it too.') }}
              </div>
              <div class="flex items-end gap-3">
                <FormControl v-model="gmail" type="text" class="flex-1"
                  :label="__('Your Gmail address')" placeholder="you@gmail.com" />
                <Button variant="solid" :loading="connecting"
                  :label="mine.connected ? __('Reconnect') : __('Connect')"
                  @click="connect" />
                <Button v-if="mine.connected" :label="__('Disconnect')" @click="disconnect" />
              </div>
              <div v-if="mine.email_account" class="mt-2 text-p-sm text-ink-gray-5">
                {{ __('Account: {0}', [mine.email_account.email_id]) }}
                <span v-if="mine.email_account.default_outgoing">
                  · {{ __('used by default') }}
                </span>
              </div>
            </div>
          </template>
        </div>
      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup>
import SettingsLayoutBase from '@/components/Layouts/SettingsLayoutBase.vue'
import { Badge, Button, FormControl, Switch, call, toast } from 'frappe-ui'
import { ref, computed, reactive, onMounted } from 'vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideKeyRound from '~icons/lucide/key-round'
import LucideMail from '~icons/lucide/mail'

const data = ref({})
const loading = ref(false)
const saving = ref(false)
const connecting = ref(false)
const copied = ref('')
const gmail = ref('')

const form = reactive({ client_id: '', client_secret: '', enable_login: false })

const mine = computed(() => data.value.my_account || {})
const redirects = computed(() => {
  const r = data.value.redirect_uris || {}
  return { login: r.login, mail: r.mail }
})

async function load() {
  loading.value = true
  try {
    data.value = await call('baton.api.google.get_google_status')
    form.client_id = data.value.client_id || ''
    form.enable_login = Boolean(data.value.login_enabled)
    gmail.value = mine.value.email_account?.email_id || ''
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    data.value = await call('baton.api.google.save_google', {
      client_id: form.client_id,
      client_secret: form.client_secret || undefined,
      enable_login: form.enable_login ? 1 : 0,
    })
    form.client_secret = ''  // never keep a secret in the page after saving
    toast.success(__('Saved'))
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not save'))
  } finally {
    saving.value = false
  }
}

async function copy(key, text) {
  await navigator.clipboard.writeText(text || '')
  copied.value = key
  setTimeout(() => (copied.value = ''), 1500)
}

/**
 * Google's consent screen has to be a full navigation, not a fetch: it sets
 * cookies and redirects back to a callback that expects to own the tab.
 */
async function connect() {
  connecting.value = true
  try {
    const res = await call('baton.api.google.connect_my_gmail', {
      email_id: gmail.value, make_default: 1,
    })
    window.location.href = res.url
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not start the connection'))
  } finally {
    connecting.value = false
  }
}

async function disconnect() {
  data.value = { ...data.value, my_account: await call('baton.api.google.disconnect_my_gmail') }
  toast.success(__('Disconnected'))
}

onMounted(load)
</script>
