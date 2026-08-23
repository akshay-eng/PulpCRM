<template>
  <div>
    <div class="mb-3 flex items-center gap-2">
      <Button variant="ghost" @click="$emit('back')">
        <template #prefix><LucideArrowLeft class="h-4 w-4" /></template>
        {{ __('All runs') }}
      </Button>
      <Badge :theme="statusTheme(run.status)" variant="subtle">{{
        run.status
      }}</Badge>
      <span class="text-sm text-ink-gray-6">{{
        run.reference_name || '—'
      }}</span>
      <span class="ml-auto text-xs text-ink-gray-5">{{ run.creation }}</span>
    </div>

    <div
      v-if="run.status === 'Waiting'"
      class="mb-3 rounded-md bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-7"
    >
      {{ __('Waiting for {0}', [waitingLabel]) }}
      <span v-if="run.resume_at" class="text-ink-gray-5">
        — {{ __('gives up {0}', [run.resume_at]) }}
      </span>
    </div>

    <div
      v-if="run.error"
      class="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      {{ run.error }}
    </div>
    <div
      v-if="run.cancelled_reason"
      class="mb-3 rounded-md bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-7"
    >
      {{ run.cancelled_reason }}
    </div>

    <div
      v-if="!run.steps.length"
      class="py-4 text-center text-sm text-ink-gray-5"
    >
      {{ __('It stopped before running anything.') }}
    </div>

    <div
      v-for="(s, i) in run.steps"
      :key="i"
      class="border-b border-outline-gray-1 py-2 last:border-0"
    >
      <div class="flex items-center gap-2">
        <component
          :is="iconFor(s.node_type)"
          class="h-4 w-4 shrink-0 text-ink-gray-6"
        />
        <span class="text-sm font-medium text-ink-gray-8">{{
          s.node_type
        }}</span>
        <span class="text-xs text-ink-gray-5">{{ s.node_id }}</span>
        <Badge :theme="stepTheme(s.status)" variant="subtle" class="ml-1">
          {{ s.status }}
        </Badge>
        <span class="ml-auto text-xs text-ink-gray-5"
          >{{ s.duration_ms }}ms</span
        >
      </div>

      <div v-if="summarise(s)" class="mt-1 pl-6 text-sm text-ink-gray-7">
        {{ summarise(s) }}
      </div>

      <div
        v-for="(l, j) in logsFor(s.node_id)"
        :key="j"
        class="mt-1 pl-6 text-xs"
        :class="l.status === 'Success' ? 'text-ink-gray-5' : 'text-ink-amber-3'"
      >
        <span class="font-mono">{{ l.action }}</span>
        <span v-if="l.decision"> · {{ l.decision }}</span>
        <span v-if="l.reason"> — {{ l.reason }}</span>
        <span v-if="l.error"> — {{ l.error }}</span>
      </div>

      <details v-if="s.output && s.output !== '{}'" class="mt-1 pl-6">
        <summary class="cursor-pointer text-xs text-ink-gray-5">
          {{ __('Raw') }}
        </summary>
        <pre
          class="mt-1 overflow-x-auto rounded bg-surface-gray-2 p-2 text-xs"
          >{{ s.output }}</pre
        >
      </details>
    </div>

    <div
      v-if="unattached.length"
      class="mt-3 border-t border-outline-gray-1 pt-2"
    >
      <div class="mb-1 text-xs font-medium text-ink-gray-5">
        {{ __('Also recorded') }}
      </div>
      <div
        v-for="(l, i) in unattached"
        :key="i"
        class="text-xs"
        :class="l.status === 'Success' ? 'text-ink-gray-5' : 'text-ink-amber-3'"
      >
        <span class="font-mono">{{ l.action }}</span>
        <span v-if="l.reason"> — {{ l.reason }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * A run, told as what happened and why.
 *
 * The audit rows are interleaved with the steps rather than listed separately
 * because a refused send is the case that matters: it produces a step with
 * almost no output and a log row carrying the actual reason. Shown apart, it
 * reads as "nothing happened".
 */
import { computed } from 'vue'
import { Badge, Button } from 'frappe-ui'
import { iconFor } from '@/components/Workflow/nodeIcons'
import LucideArrowLeft from '~icons/lucide/arrow-left'

const props = defineProps({ run: { type: Object, required: true } })
defineEmits(['back'])

const statusTheme = (s) =>
  ({ Completed: 'green', Failed: 'red', Cancelled: 'gray', Expired: 'orange' })[
    s
  ] || 'blue'
const stepTheme = (s) =>
  ({ Success: 'green', Failed: 'red', Skipped: 'orange' })[s] || 'gray'

const waitingLabel = computed(
  () =>
    ({
      Reply: __('a reply'),
      Approval: __('an approval'),
      Timer: __('a delay'),
    })[props.run.waiting_for] || __('something'),
)

const logsFor = (nodeId) =>
  (props.run.log || []).filter((l) => l.node_id === nodeId)
const unattached = computed(() =>
  (props.run.log || []).filter((l) => !l.node_id),
)

/** The one line worth reading, pulled out of the step's JSON. */
function summarise(step) {
  let out
  try {
    out = JSON.parse(step.output || '{}')
  } catch {
    return ''
  }
  if (out.skipped) return __('Skipped: {0}', [out.skipped])
  if (out.drafted) return __('Drafted for approval')
  if (out.blocked) return __('Blocked: {0}', [out.blocked])
  if (out.to && out.sent) return __('Sent to {0}', [out.to])
  if (out.offered) return __('Offered {0} times', [out.offered.length])
  if (out.held) return __('Held {0}', [out.slot])
  if (out.event) return __('Booked')
  if (out.action) return __('Agent chose to {0}', [out.action])
  if (out.waiting_seconds) return __('Waiting {0}s', [out.waiting_seconds])
  if (out.result !== undefined) return String(out.result).slice(0, 200)
  return ''
}
</script>
