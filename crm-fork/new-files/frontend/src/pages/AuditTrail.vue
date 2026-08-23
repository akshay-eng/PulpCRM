<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[{ label: __('Audit trail') }]" />
    </template>
    <template #right-header>
      <Button :label="__('Refresh')" :loading="loading" @click="load(false)">
        <template #prefix><TablerRefresh class="size-4" /></template>
      </Button>
    </template>
  </LayoutHeader>

  <main class="flex-1 overflow-y-auto bg-surface-gray-1 px-6 py-6">
    <div class="mx-auto max-w-5xl">
      <div class="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 class="text-2xl font-semibold text-ink-gray-9">
            {{ __('Audit trail') }}
          </h1>
          <p class="mt-1 max-w-2xl text-sm text-ink-gray-6">
            {{
              __(
                'A permission-aware history of who changed CRM records, bots, and workflows, what changed, where it came from, and any reason that was provided.',
              )
            }}
          </p>
        </div>
        <div class="flex items-center gap-2">
          <select
            v-model="doctypeFilter"
            class="h-9 rounded-lg border border-outline-gray-2 bg-surface-white px-3 text-sm text-ink-gray-8 outline-none focus:border-outline-orange-1"
            @change="changeDoctype"
          >
            <option value="">{{ __('All record types') }}</option>
            <option v-for="doctype in doctypes" :key="doctype" :value="doctype">
              {{ doctypeLabel(doctype) }}
            </option>
          </select>
          <div class="relative">
            <TablerSearch
              class="pointer-events-none absolute left-3 top-2.5 size-4 text-ink-gray-4"
            />
            <input
              v-model="search"
              class="h-9 w-56 rounded-lg border border-outline-gray-2 bg-surface-white pl-9 pr-3 text-sm text-ink-gray-8 outline-none placeholder:text-ink-gray-4 focus:border-outline-orange-1"
              :placeholder="__('Search this history')"
            />
          </div>
        </div>
      </div>

      <div
        v-if="referenceName"
        class="mb-4 flex items-center justify-between rounded-lg border border-outline-orange-1 bg-surface-orange-1 px-3 py-2 text-sm text-ink-gray-7"
      >
        <span>
          {{ __('Showing history for {0}', [referenceName]) }}
        </span>
        <button
          class="font-medium text-ink-orange-3 hover:underline"
          @click="clearRecordFilter"
        >
          {{ __('Show all') }}
        </button>
      </div>

      <div
        v-if="loading && !entries.length"
        class="grid min-h-64 place-items-center rounded-xl border border-outline-gray-2 bg-surface-white"
      >
        <div class="flex items-center gap-2 text-sm text-ink-gray-5">
          <TablerLoader class="size-4 animate-spin" />
          {{ __('Loading audit history…') }}
        </div>
      </div>

      <div
        v-else-if="!visibleEntries.length"
        class="grid min-h-64 place-items-center rounded-xl border border-outline-gray-2 bg-surface-white p-8 text-center"
      >
        <div>
          <div
            class="mx-auto grid size-10 place-items-center rounded-xl bg-surface-gray-2"
          >
            <TablerHistory class="size-5 text-ink-gray-5" />
          </div>
          <div class="mt-3 text-sm font-medium text-ink-gray-8">
            {{ __('No audit entries found') }}
          </div>
          <p class="mt-1 text-xs text-ink-gray-5">
            {{
              __(
                'Changes will appear here as records and automations are edited.',
              )
            }}
          </p>
        </div>
      </div>

      <div
        v-else
        class="overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-white"
      >
        <article
          v-for="entry in visibleEntries"
          :key="entry.name"
          class="border-b border-outline-gray-1 px-5 py-4 last:border-0"
        >
          <div class="flex items-start gap-3">
            <div
              class="mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg"
              :class="eventTone(entry.event)"
            >
              <component :is="eventIcon(entry.event)" class="size-4" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="text-sm font-medium text-ink-gray-9">
                  {{ entry.actor_id || __('System') }}
                </span>
                <span class="text-sm text-ink-gray-6">
                  {{ eventLabel(entry.event) }}
                </span>
                <button
                  class="max-w-sm truncate text-sm font-medium text-ink-orange-3 hover:underline"
                  @click="openRecord(entry)"
                >
                  {{ entry.title || entry.reference_name }}
                </button>
                <Badge
                  :label="doctypeLabel(entry.reference_doctype)"
                  variant="subtle"
                />
                <Badge
                  v-if="entry.danger_mode"
                  :label="__('Danger mode')"
                  theme="red"
                  variant="subtle"
                />
              </div>

              <div
                class="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-ink-gray-5"
              >
                <span>{{ formatDate(entry.creation) }}</span>
                <span>·</span>
                <span>{{ entry.source }}</span>
                <template v-if="entry.workflow || entry.bot">
                  <span>·</span>
                  <span>{{ entry.workflow || entry.bot }}</span>
                </template>
              </div>

              <div v-if="entry.changes?.length" class="mt-3 space-y-1.5">
                <div
                  v-for="change in entry.changes"
                  :key="change.field"
                  class="grid grid-cols-[minmax(100px,160px)_1fr] gap-3 rounded-lg bg-surface-gray-1 px-3 py-2 text-xs"
                >
                  <span class="font-medium text-ink-gray-7">{{
                    change.label
                  }}</span>
                  <span class="min-w-0 text-ink-gray-6">
                    <span
                      v-if="hasValue(change.before)"
                      class="break-words line-through opacity-70"
                    >
                      {{ formatValue(change.before) }}
                    </span>
                    <TablerArrowRight
                      v-if="hasValue(change.before) && hasValue(change.after)"
                      class="mx-1 inline size-3"
                    />
                    <span
                      v-if="hasValue(change.after)"
                      class="break-words font-medium text-ink-gray-8"
                    >
                      {{ formatValue(change.after) }}
                    </span>
                    <span
                      v-if="!hasValue(change.before) && !hasValue(change.after)"
                      >—</span
                    >
                  </span>
                </div>
              </div>

              <div class="mt-2 text-xs">
                <span class="text-ink-gray-5">{{ __('Reason') }}:</span>
                <span
                  :class="
                    entry.reason ? 'text-ink-gray-7' : 'italic text-ink-gray-4'
                  "
                >
                  {{ entry.reason || __('No reason provided') }}
                </span>
              </div>
            </div>
          </div>
        </article>
      </div>

      <div v-if="hasMore && !search" class="mt-4 flex justify-center">
        <Button :label="__('Load more')" :loading="loading" @click="loadMore" />
      </div>
    </div>
  </main>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import { Badge, Breadcrumbs, Button, call, toast } from 'frappe-ui'
import { computed, markRaw, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  IconArrowRight as TablerArrowRight,
  IconEdit as TablerEdit,
  IconFilePlus as TablerCreate,
  IconHistory as TablerHistory,
  IconLoader2 as TablerLoader,
  IconMessage as TablerMessage,
  IconRefresh as TablerRefresh,
  IconSearch as TablerSearch,
  IconTrash as TablerTrash,
  IconUserCheck as TablerAssign,
} from '@tabler/icons-vue'

const route = useRoute()
const router = useRouter()
const entries = ref([])
const doctypes = ref([])
const loading = ref(false)
const hasMore = ref(false)
const nextStart = ref(0)
const search = ref('')
const doctypeFilter = ref(String(route.query.doctype || ''))
const referenceName = ref(String(route.query.name || ''))

const ROUTES = {
  'CRM Lead': 'Lead',
  'CRM Deal': 'Deal',
  Contact: 'Contact',
  'CRM Organization': 'Organization',
  'Baton Bot': 'Bot',
  'Baton Workflow': 'Workflow',
}

const visibleEntries = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return entries.value
  return entries.value.filter((entry) =>
    [
      entry.actor_id,
      entry.title,
      entry.reference_name,
      entry.reference_doctype,
      entry.source,
      entry.reason,
    ].some((value) =>
      String(value || '')
        .toLowerCase()
        .includes(needle),
    ),
  )
})

async function load(append = false) {
  if (loading.value) return
  loading.value = true
  try {
    const raw = await call('baton.api.audit.get_audit_trail', {
      reference_doctype: doctypeFilter.value || undefined,
      reference_name: referenceName.value || undefined,
      start: append ? nextStart.value : 0,
      limit: 50,
    })
    const result = raw?.message ?? raw
    entries.value = append
      ? [...entries.value, ...(result.entries || [])]
      : result.entries || []
    doctypes.value = result.doctypes || doctypes.value
    nextStart.value = result.next_start || 0
    hasMore.value = Boolean(result.has_more)
  } catch (error) {
    toast.error(
      error.messages?.[0] ||
        error.message ||
        __('Could not load audit history'),
    )
  } finally {
    loading.value = false
  }
}

function changeDoctype() {
  referenceName.value = ''
  router.replace({
    query: doctypeFilter.value ? { doctype: doctypeFilter.value } : {},
  })
  return load(false)
}

function loadMore() {
  return load(true)
}

function clearRecordFilter() {
  referenceName.value = ''
  router.replace({
    query: doctypeFilter.value ? { doctype: doctypeFilter.value } : {},
  })
  load(false)
}

function doctypeLabel(doctype) {
  return (
    {
      'CRM Lead': __('Lead'),
      'CRM Deal': __('Deal'),
      Contact: __('Contact'),
      'CRM Organization': __('Company'),
      'CRM Task': __('Task'),
      'FCRM Note': __('Note'),
      'CRM Call Log': __('Call'),
      'Baton Bot': __('Bot'),
      'Baton Workflow': __('Workflow'),
    }[doctype] || doctype
  )
}

function eventLabel(event) {
  return (
    {
      created: __('created'),
      updated: __('updated'),
      deleted: __('deleted'),
      renamed: __('renamed'),
      assigned: __('changed the assignment on'),
      commented: __('commented on'),
    }[event] || event
  )
}

function eventIcon(event) {
  return markRaw(
    {
      created: TablerCreate,
      deleted: TablerTrash,
      assigned: TablerAssign,
      commented: TablerMessage,
    }[event] || TablerEdit,
  )
}

function eventTone(event) {
  if (event === 'deleted') return 'bg-surface-red-1 text-ink-red-4'
  if (event === 'created') return 'bg-surface-green-1 text-ink-green-3'
  return 'bg-surface-orange-1 text-ink-orange-3'
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== ''
}

function formatValue(value) {
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return text.length > 500 ? `${text.slice(0, 500)}…` : text
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(String(value).replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function openRecord(entry) {
  const name = ROUTES[entry.reference_doctype]
  if (!name || entry.event === 'deleted') return
  const param = {
    Lead: 'leadId',
    Deal: 'dealId',
    Contact: 'contactId',
    Organization: 'organizationId',
    Bot: 'botId',
    Workflow: 'workflowId',
  }[name]
  router.push({ name, params: { [param]: entry.reference_name } })
}

onMounted(() => load(false))
</script>
