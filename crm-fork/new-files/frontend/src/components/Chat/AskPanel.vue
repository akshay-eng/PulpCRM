<template>
  <aside
    v-if="open"
    class="flex w-[420px] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-white"
  >
    <div
      class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3"
    >
      <div class="flex items-center gap-2">
        <TablerSparkles class="h-4 w-4 text-orange-500" />
        <span class="text-base font-medium text-ink-gray-8">{{
          __('Ask Pulp')
        }}</span>
      </div>
      <div class="flex items-center gap-1">
        <Button
          variant="ghost"
          :label="__('New chat')"
          size="sm"
          @click="reset"
        >
          <template #prefix><TablerPlus class="h-3.5 w-3.5" /></template>
        </Button>
        <button
          class="rounded-md p-1 text-ink-gray-5 hover:bg-surface-gray-2 hover:text-ink-gray-8"
          :aria-label="__('Close Ask Pulp')"
          @click="close"
        >
          <TablerX class="h-4 w-4" />
        </button>
      </div>
    </div>

    <div class="border-b border-outline-gray-2 bg-surface-gray-1 px-3 py-2">
      <AICredentialPicker
        v-model="credentialId"
        :label="__('Ask with')"
        compact
      />
    </div>

    <div ref="scroller" class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
      <div
        v-if="!hasReadyCredential"
        class="rounded-xl border border-outline-orange-2 bg-surface-orange-1 p-4"
      >
        <div class="flex items-start gap-3">
          <span
            class="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-orange-2 text-ink-orange-3"
          >
            <TablerKey class="size-4.5" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium text-ink-gray-9">
              {{ __('Add an LLM key to start chatting') }}
            </div>
            <p class="mt-1 text-xs leading-5 text-ink-gray-6">
              {{
                __(
                  'Your key stays in this browser. Pulp sends it only with the AI request and never stores it on the server.',
                )
              }}
            </p>
            <Button
              class="mt-3"
              variant="solid"
              :label="__('Configure an AI key')"
              @click="openKeySettings"
            >
              <template #prefix><TablerKey class="size-4" /></template>
            </Button>
          </div>
        </div>
      </div>

      <div v-else-if="!turns.length" class="pt-4">
        <div class="mb-1 text-sm font-medium text-ink-gray-7">
          {{ __('What can I help you get done?') }}
        </div>
        <div class="mb-4 text-xs leading-5 text-ink-gray-5">
          {{
            __(
              'Find and summarize CRM data, export lists, or prepare record changes in plain English.',
            )
          }}
        </div>
        <button
          v-for="suggestion in suggestions"
          :key="suggestion"
          class="mb-1.5 flex w-full items-center gap-2 rounded-lg border border-outline-gray-2 px-2.5 py-2 text-left text-xs text-ink-gray-7 hover:border-outline-orange-1 hover:bg-surface-orange-1"
          @click="ask(suggestion)"
        >
          <TablerWand class="h-3.5 w-3.5 shrink-0 text-orange-500" />
          {{ suggestion }}
        </button>
      </div>

      <div v-for="(turn, index) in turns" :key="index">
        <div class="mb-2 flex justify-end">
          <div
            class="max-w-[85%] rounded-lg bg-surface-gray-3 px-3 py-1.5 text-sm text-ink-gray-8"
          >
            {{ turn.question }}
          </div>
        </div>

        <div
          v-if="turn.pending"
          class="flex items-center gap-2 text-xs text-ink-gray-5"
        >
          <TablerLoader class="h-3.5 w-3.5 animate-spin" />
          {{ __('Thinking…') }}
        </div>

        <div
          v-else-if="turn.error"
          class="rounded-lg border border-outline-red-1 bg-surface-red-1 px-3 py-2 text-xs text-ink-red-4"
        >
          {{ turn.error }}
        </div>

        <template v-else>
          <div class="mb-2 text-sm leading-5 text-ink-gray-8">
            {{ turn.answer }}
          </div>

          <div
            v-if="turn.rows?.length"
            class="overflow-hidden rounded-lg border border-outline-gray-2"
          >
            <div class="max-h-72 overflow-auto">
              <table class="w-full text-xs">
                <thead class="sticky top-0 bg-surface-gray-2">
                  <tr>
                    <th
                      v-for="field in turn.fields"
                      :key="field"
                      class="px-2 py-1.5 text-left font-medium text-ink-gray-6"
                    >
                      {{ fieldLabel(field) }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(row, rowIndex) in turn.rows"
                    :key="rowIndex"
                    class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
                    @click="openRecord(turn.doctype, row.name)"
                  >
                    <td
                      v-for="field in turn.fields"
                      :key="field"
                      class="px-2 py-1.5 text-ink-gray-7"
                    >
                      {{ format(row[field]) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div
              class="flex items-center justify-between border-t border-outline-gray-1 bg-surface-gray-1 px-2 py-1"
            >
              <span class="text-[11px] text-ink-gray-5">
                {{ turn.doctype }} · {{ turn.row_count }}
                {{ turn.export ? __('preview rows') : __('rows') }}
              </span>
              <button
                v-if="turn.query"
                class="text-[11px] text-ink-gray-5 underline hover:text-ink-gray-7"
                @click="turn.showQuery = !turn.showQuery"
              >
                {{ turn.showQuery ? __('hide query') : __('show query') }}
              </button>
            </div>
            <pre
              v-if="turn.showQuery && turn.query"
              class="max-h-40 overflow-auto border-t border-outline-gray-1 bg-surface-gray-2 px-2 py-1.5 text-[11px] text-ink-gray-6"
              >{{ JSON.stringify(turn.query, null, 1) }}</pre
            >
          </div>

          <div
            v-else-if="turn.doctype && !turn.pendingAction"
            class="text-xs text-ink-gray-5"
          >
            {{ __('No matching records.') }}
          </div>

          <div
            v-if="turn.export"
            class="mt-2 flex items-center justify-between gap-3 rounded-lg border border-outline-green-1 bg-surface-green-1 px-3 py-2"
          >
            <div
              class="flex min-w-0 items-center gap-2 text-xs text-ink-green-3"
            >
              <TablerDownload class="size-4 shrink-0" />
              <span>{{
                __('Your {0} export is ready.', [turn.export.file_format])
              }}</span>
            </div>
            <Button
              variant="ghost"
              :label="__('Download')"
              @click="download(turn.export)"
            />
          </div>

          <div
            v-if="turn.pendingAction"
            class="mt-2 rounded-xl border border-outline-orange-2 bg-surface-orange-1 p-3"
          >
            <div class="flex items-start gap-2">
              <TablerShieldCheck
                class="mt-0.5 size-4 shrink-0 text-orange-600"
              />
              <div class="min-w-0 flex-1">
                <div class="text-xs font-medium text-ink-gray-9">
                  {{ actionHeading(turn.pendingAction) }}
                </div>
                <div class="mt-1 text-xs leading-5 text-ink-gray-6">
                  {{ actionDetails(turn.pendingAction) }}
                </div>
              </div>
            </div>

            <div
              v-if="turn.pendingAction.status === 'pending'"
              class="mt-3 flex gap-2"
            >
              <Button
                variant="solid"
                :label="__('Confirm')"
                :loading="turn.actionBusy"
                @click="resolveAction(turn, 'confirm')"
              />
              <Button
                variant="ghost"
                :label="__('Cancel')"
                :disabled="turn.actionBusy"
                @click="resolveAction(turn, 'cancel')"
              />
            </div>
            <div
              v-if="turn.actionError"
              class="mt-2 rounded-md bg-surface-red-1 px-2 py-1.5 text-xs text-ink-red-4"
            >
              {{ turn.actionError }}
            </div>
            <div
              v-if="turn.pendingAction.status !== 'pending'"
              class="mt-2 flex items-center gap-1.5 text-xs font-medium"
              :class="
                turn.pendingAction.status === 'completed'
                  ? 'text-ink-green-3'
                  : 'text-ink-gray-6'
              "
            >
              <TablerCircleCheck
                v-if="turn.pendingAction.status === 'completed'"
                class="size-4"
              />
              <TablerCircleX v-else class="size-4" />
              {{
                turn.pendingAction.status === 'completed'
                  ? __('Completed')
                  : __('Cancelled')
              }}
            </div>
          </div>
        </template>
      </div>
    </div>

    <div class="border-t border-outline-gray-2 p-3">
      <div
        class="flex items-end gap-2 rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5 focus-within:border-outline-orange-1"
      >
        <textarea
          v-model="draft"
          rows="1"
          :disabled="!hasReadyCredential"
          :placeholder="
            hasReadyCredential
              ? __('Ask Pulp to find or update CRM data…')
              : __('Configure an AI key to start…')
          "
          class="max-h-28 flex-1 resize-none bg-transparent text-sm text-ink-gray-8 placeholder:text-ink-gray-4 focus:outline-none disabled:cursor-not-allowed"
          @keydown.enter.exact.prevent="ask()"
        ></textarea>
        <button
          class="rounded-md p-1 text-ink-gray-5 hover:text-orange-600 disabled:opacity-40"
          :disabled="!hasReadyCredential || !draft.trim() || busy"
          :aria-label="__('Send')"
          @click="ask()"
        >
          <TablerArrowUp class="h-4 w-4" />
        </button>
      </div>
      <div class="mt-1.5 flex items-center gap-1 text-[11px] text-ink-gray-5">
        <TablerLock class="size-3" />
        {{ __('Reads with your permissions and asks before making changes.') }}
      </div>
    </div>
  </aside>
</template>

<script setup>
import { Button, call } from 'frappe-ui'
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  IconArrowUp as TablerArrowUp,
  IconCircleCheck as TablerCircleCheck,
  IconCircleX as TablerCircleX,
  IconDownload as TablerDownload,
  IconKey as TablerKey,
  IconLoader2 as TablerLoader,
  IconLock as TablerLock,
  IconPlus as TablerPlus,
  IconShieldCheck as TablerShieldCheck,
  IconSparkles as TablerSparkles,
  IconWand as TablerWand,
  IconX as TablerX,
} from '@tabler/icons-vue'
import AICredentialPicker from '@/components/AI/AICredentialPicker.vue'
import { activeSettingsPage, showSettings } from '@/composables/settings'
import { useAICredentials } from '@/stores/aiCredentials'
import { downloadExport } from '@/utils/chatActions'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close'])

const router = useRouter()
const turns = ref([])
const draft = ref('')
const busy = ref(false)
const session = ref(null)
const scroller = ref(null)
const { credentials, getSelection, setSelection, isReady, requestCredential } =
  useAICredentials()
const credentialId = ref(getSelection('ask'))
const readyCredentials = computed(() =>
  credentials.value.filter((credential) => isReady(credential.id)),
)
const hasReadyCredential = computed(() => isReady(credentialId.value))

const suggestions = [
  'Show the 5 most recently modified deals',
  'Summarize the open leads that need attention',
  'Export all open leads as CSV',
  'Create a high-priority follow-up task for tomorrow',
]

const ROUTES = {
  'CRM Lead': 'Lead',
  'CRM Deal': 'Deal',
  Contact: 'Contact',
  'CRM Organization': 'Organization',
}

function format(value) {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  return text.length > 42 ? `${text.slice(0, 42)}…` : text
}

function fieldLabel(field) {
  return String(field || '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function openRecord(doctype, name) {
  const route = ROUTES[doctype]
  if (!route || !name) return
  router.push({ name: route, params: { [`${route.toLowerCase()}Id`]: name } })
}

function reset() {
  turns.value = []
  session.value = null
  draft.value = ''
}

function close() {
  emit('close')
}

function openKeySettings() {
  activeSettingsPage.value = 'AI models'
  showSettings.value = true
}

async function scrollDown() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

function download(spec) {
  downloadExport(spec)
}

function actionHeading(action) {
  const labels = {
    update: __('Confirm record update'),
    create: __('Confirm new record'),
    assign: __('Confirm assignment'),
    add_comment: __('Confirm comment'),
    convert_lead: __('Confirm lead conversion'),
  }
  return labels[action.action] || __('Confirm CRM action')
}

function actionDetails(action) {
  if (action.action === 'update') {
    return Object.entries(action.values || {})
      .map(([field, value]) => `${fieldLabel(field)} → ${format(value)}`)
      .join(', ')
  }
  if (action.action === 'create') {
    return Object.entries(action.values || {})
      .map(([field, value]) => `${fieldLabel(field)}: ${format(value)}`)
      .join(', ')
  }
  if (action.action === 'assign') {
    return __('Assign {0} record(s) to {1}.', [
      action.names?.length || 0,
      action.assignee,
    ])
  }
  if (action.action === 'add_comment') {
    return __('Add this comment to {0} record(s): “{1}”', [
      action.names?.length || 0,
      action.comment,
    ])
  }
  if (action.action === 'convert_lead') {
    return __('Convert {0} lead(s) into deals.', [action.names?.length || 0])
  }
  return action.explanation || __('Review this action before it runs.')
}

async function resolveAction(turn, decision) {
  if (turn.actionBusy || turn.pendingAction?.status !== 'pending') return
  turn.actionBusy = true
  turn.actionError = ''
  try {
    const raw = await call('baton.api.chat.execute_action', {
      action_id: turn.pendingAction.id,
      decision,
    })
    const result = raw?.message ?? raw
    turn.pendingAction.status = result.status
    turn.answer = result.answer
    if (result.results?.length && decision === 'confirm') {
      turn.rows = result.results
      turn.fields = [...new Set(result.results.flatMap(Object.keys))]
      turn.row_count = result.results.length
      turn.doctype = result.results[0].doctype || turn.doctype
    }
  } catch (error) {
    turn.actionError =
      error.messages?.[0] ||
      error.exc_type ||
      error.message ||
      __('The action could not be completed.')
  } finally {
    turn.actionBusy = false
    await scrollDown()
  }
}

async function ask(text) {
  const question = (text ?? draft.value).trim()
  if (!question || busy.value) return
  if (!hasReadyCredential.value) {
    openKeySettings()
    return
  }

  draft.value = ''
  busy.value = true
  const turn = reactive({ question, pending: true, showQuery: false })
  turns.value.push(turn)
  await scrollDown()

  try {
    const raw = await call('baton.api.chat.ask', {
      question,
      session: session.value || undefined,
      credential: requestCredential(credentialId.value),
    })
    const result = raw?.message ?? raw
    session.value = result.session
    Object.assign(turn, {
      pending: false,
      answer: result.answer,
      rows: result.rows,
      fields: result.fields,
      doctype: result.doctype,
      row_count: result.row_count,
      query: result.query,
      export: result.export,
      pendingAction: result.pending_action,
      actionBusy: false,
    })
    if (result.export) download(result.export)
  } catch (error) {
    Object.assign(turn, {
      pending: false,
      error:
        error.messages?.[0] ||
        error.exc_type ||
        error.message ||
        __('Something went wrong while asking Pulp.'),
    })
  } finally {
    busy.value = false
    await scrollDown()
  }
}

watch(
  readyCredentials,
  (ready) => {
    if (!hasReadyCredential.value && ready.length) {
      credentialId.value = ready[0].id
    }
  },
  { immediate: true },
)
watch(
  () => props.open,
  (isOpen) => isOpen && scrollDown(),
)
watch(credentialId, (value) => setSelection('ask', value))
</script>
