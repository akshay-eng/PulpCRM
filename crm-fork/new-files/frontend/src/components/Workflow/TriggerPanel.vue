<template>
  <div class="rounded-lg border border-outline-gray-2 bg-surface-white shadow-sm">
    <div class="flex items-center gap-2 px-3 py-2"
      :class="open ? 'border-b border-outline-gray-2' : ''">
      <LucideZap class="h-4 w-4 shrink-0 text-ink-gray-6" />
      <button class="min-w-0 flex-1 text-left" @click="open = !open">
        <div class="text-p-base font-medium text-ink-gray-8">
          {{ title || __('When this happens') }}
        </div>
        <!--
          Collapsed by default once it is set. An always-open card sat on top of
          the graph and covered whatever node was underneath it -- and after the
          first minute nobody needs to read their own trigger again.
        -->
        <div v-if="!open" class="truncate text-p-sm text-ink-gray-5">{{ summary }}</div>
      </button>
      <Button variant="ghost" @click="add">
        <template #icon><LucidePlus class="h-4 w-4" /></template>
      </Button>
      <button class="shrink-0 text-ink-gray-5" @click="open = !open">
        <LucideChevronDown class="h-4 w-4 transition" :class="open ? 'rotate-180' : ''" />
      </button>
    </div>

    <div v-if="open && !triggers.length" class="px-3 py-3 text-p-sm text-ink-gray-5">
      {{ __('Nothing set, so this only runs when you start it yourself.') }}
      <button class="mt-1 block text-ink-gray-7 underline" @click="add">
        {{ __('Add a trigger') }}
      </button>
    </div>

    <!-- template wrapper: v-if and v-for on one element is ambiguous in Vue 3. -->
    <template v-if="open">
    <div
      v-for="(t, i) in triggers"
      :key="i"
      class="border-b border-outline-gray-1 px-3 py-2.5 last:border-0"
    >
      <div class="flex items-center gap-2">
        <FormControl
          v-model="t.trigger_type"
          type="select"
          :options="TRIGGER_TYPES"
          class="flex-1"
        />
        <button
          class="text-ink-gray-5 hover:text-red-600"
          :title="__('Remove trigger')"
          @click="triggers.splice(i, 1)"
        >
          <LucideX class="h-3.5 w-3.5" />
        </button>
      </div>

      <template v-if="t.trigger_type === 'Document Event'">
        <FormControl
          v-model="t.trigger_doctype"
          type="select"
          :options="doctypeOptions"
          :label="__('Record type')"
          class="mt-2"
        />
        <FormControl
          v-model="t.trigger_event"
          type="select"
          :options="EVENT_OPTIONS"
          :label="__('When it')"
          class="mt-2"
        />
        <FormControl
          v-if="t.trigger_event === 'on_update'"
          v-model="t.field_changed"
          type="text"
          :label="__('Only when this field changes')"
          :placeholder="__('e.g. status')"
          class="mt-2"
        />
      </template>

      <template v-else-if="t.trigger_type === 'Scheduled'">
        <FormControl
          v-model="t.cron"
          type="text"
          :label="__('Cron')"
          placeholder="0 9 * * *"
          class="mt-2"
        />
        <div class="mt-1 text-xs text-ink-gray-5">{{ cronHint(t.cron) }}</div>
      </template>

      <template v-else-if="t.trigger_type === 'Event'">
        <FormControl
          v-model="t.event_name"
          type="select"
          :options="events"
          :label="__('Event name')"
          class="mt-2"
        />
      </template>

      <template v-else-if="t.trigger_type === 'Webhook'">
        <div class="mt-2 text-xs text-ink-gray-5">
          {{ __('A URL is generated when you save.') }}
        </div>
        <div
          v-if="t.webhook_path"
          class="mt-1 truncate rounded bg-surface-gray-2 px-2 py-1 font-mono text-xs text-ink-gray-7"
        >
          /api/method/baton.api.trigger_webhook.receive?path={{ t.webhook_path }}
        </div>
      </template>
    </div>
    </template>
  </div>
</template>

<script setup>
import { Button, FormControl } from 'frappe-ui'
import LucideZap from '~icons/lucide/zap'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'
import LucideChevronDown from '~icons/lucide/chevron-down'

import { ref, computed, watch } from 'vue'

const props = defineProps({
  triggers: { type: Array, required: true },
  doctypes: { type: Array, default: () => [] },
  events: { type: Array, default: () => [] },
  title: { type: String, default: '' },
  // A bot can also be woken by a customer writing in; a workflow starts from a
  // record, so it has no such trigger and should not be offered one.
  allowInbound: { type: Boolean, default: false },
})

const TRIGGER_TYPES = computed(() => [
  'Document Event', 'Scheduled', ...(props.allowInbound ? ['Inbound Message'] : []),
  'Event', 'Webhook', 'Manual',
].filter((t) => props.events.length || t !== 'Event'))

// "CRM Lead" is what the database calls it. Nobody else does.
const FRIENDLY = {
  'CRM Lead': 'Lead', 'CRM Deal': 'Deal', 'CRM Task': 'Task',
  'CRM Organization': 'Organization', 'CRM Call Log': 'Call log',
  'FCRM Note': 'Note', Contact: 'Contact',
}
const doctypeOptions = computed(() =>
  props.doctypes.map((d) => ({ label: __(FRIENDLY[d] || d), value: d })),
)

// The hook names are Frappe's. "on_trash" is not a thing anyone says out loud.
const EVENT_OPTIONS = [
  { label: __('is created'), value: 'after_insert' },
  { label: __('is changed'), value: 'on_update' },
  { label: __('is deleted'), value: 'on_trash' },
]

const open = ref(true)

/**
 * Settle once, on the first render that has real data: expanded when there is
 * nothing configured (so the missing piece is in front of you), collapsed when
 * there is (so it stops sitting on top of the graph). After that it is the
 * user's to open and close -- re-deciding on every change would fight them.
 */
const settled = ref(false)
watch(
  () => props.triggers.length,
  (n) => {
    if (settled.value || !n) return
    settled.value = true
    open.value = false
  },
  { immediate: true },
)

const summary = computed(() => {
  if (!props.triggers.length) return __('Nothing yet — runs only by hand')
  const parts = props.triggers.map((t) => {
    if (t.trigger_type === 'Document Event') {
      const what = __(FRIENDLY[t.trigger_doctype] || t.trigger_doctype || '?')
      const when = EVENT_OPTIONS.find((e) => e.value === t.trigger_event)?.label
        || t.trigger_event
      return `${what} ${when}`
    }
    if (t.trigger_type === 'Scheduled') return __('On a schedule')
    if (t.trigger_type === 'Inbound Message') return __('They write in')
    if (t.trigger_type === 'Webhook') return __('A webhook fires')
    return t.trigger_type
  })
  return parts.join(' · ')
})

function add() {
  // Claim the settle before pushing. Without this the length watcher below sees
  // 0 -> 1 and collapses the card the instant you click "Add a trigger" --
  // hiding the form you just asked for.
  settled.value = true
  open.value = true
  props.triggers.push({
    enabled: 1,
    trigger_type: 'Document Event',
    trigger_doctype: props.doctypes[0] || 'CRM Lead',
    trigger_event: 'after_insert',
  })
}

// Enough of a read-back that a typo is obvious, without pulling in a cron parser.
function cronHint(cron) {
  if (!cron) return __('Five fields: minute hour day month weekday.')
  const parts = String(cron).trim().split(/\s+/)
  if (parts.length !== 5) return __('A cron expression needs exactly five fields.')
  const [m, h] = parts
  if (/^\d+$/.test(m) && /^\d+$/.test(h)) {
    return __('Runs at {0}:{1} on matching days.', [h.padStart(2, '0'), m.padStart(2, '0')])
  }
  return __('Runs on the schedule you have described.')
}
</script>
