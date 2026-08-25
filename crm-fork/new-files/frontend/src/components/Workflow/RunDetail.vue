<template>
  <div>
    <div class="mb-4 flex items-center gap-2">
      <Button variant="ghost" @click="$emit('back')">
        <template #prefix><LucideArrowLeft class="h-4 w-4" /></template>
        {{ __('All runs') }}
      </Button>
      <Badge :theme="statusTheme(run.status)" variant="subtle">{{ run.status }}</Badge>
      <span class="text-sm font-medium text-ink-gray-8">{{ run.reference_name || '—' }}</span>
      <span class="ml-auto text-xs text-ink-gray-5" :title="formatDate(run.creation)">
        {{ timeAgo(run.creation) }}
      </span>
    </div>

    <div
      v-if="run.status === 'Waiting'"
      class="mb-4 flex items-center gap-2 rounded-md bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-7"
    >
      <LucideClock class="h-4 w-4 shrink-0 text-ink-gray-5" />
      <span>{{ __('Waiting for {0}', [waitingLabel]) }}</span>
      <span v-if="run.resume_at" class="text-ink-gray-5">
        — {{ __('resumes {0}', [timeAgo(run.resume_at)]) }}
      </span>
    </div>

    <div v-if="run.error" class="mb-4 flex items-start gap-2 rounded-md bg-surface-red-1 px-3 py-2 text-sm text-ink-red-6">
      <LucideOctagonX class="mt-0.5 h-4 w-4 shrink-0" />
      <span>{{ run.error }}</span>
    </div>
    <div
      v-if="run.cancelled_reason"
      class="mb-4 rounded-md bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-7"
    >
      {{ run.cancelled_reason }}
    </div>

    <div v-if="!run.steps.length" class="py-6 text-center text-sm text-ink-gray-5">
      {{ __('It stopped before running anything.') }}
    </div>

    <div class="relative">
      <div v-for="(s, i) in run.steps" :key="i" class="relative flex gap-3 pb-5 last:pb-0">
        <div
          v-if="i < run.steps.length - 1"
          class="absolute bottom-0 left-[15px] top-8 border-l border-outline-gray-2"
        />
        <div
          class="z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border"
          :class="bubbleClasses(s.status)"
        >
          <component :is="stepIcon(s)" class="h-4 w-4" />
        </div>

        <div class="min-w-0 flex-1 pt-1">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-ink-gray-8">{{ stepTitle(s) }}</span>
            <span v-if="isBot(s)" class="text-xs text-ink-gray-4">{{ s.node_id }}</span>
            <span v-else class="text-xs text-ink-gray-5">{{ s.node_id }}</span>
            <Badge :theme="stepTheme(s.status)" variant="subtle" class="ml-1">
              {{ s.status }}
            </Badge>
            <span class="ml-auto shrink-0 text-xs text-ink-gray-4">{{ s.duration_ms }}ms</span>
          </div>

          <div v-if="thoughtFor(s)" class="mt-1.5 text-sm italic text-ink-gray-5">
            “{{ thoughtFor(s) }}”
          </div>

          <div v-if="summarise(s)" class="mt-1.5 text-sm" :class="resultClasses(s)">
            {{ summarise(s) }}
          </div>

          <div
            v-for="(l, j) in logsFor(s.node_id)"
            :key="j"
            class="mt-1.5 text-xs"
            :class="l.status === 'Success' ? 'text-ink-gray-5' : 'text-ink-amber-3'"
          >
            <span class="font-mono">{{ l.action }}</span>
            <span v-if="l.decision"> · {{ l.decision }}</span>
            <span v-if="l.reason"> — {{ l.reason }}</span>
            <span v-if="l.error"> — {{ l.error }}</span>
          </div>

          <details v-if="hasRaw(s)" class="mt-1.5 group">
            <summary
              class="inline-flex cursor-pointer items-center gap-1 text-xs text-ink-gray-4 hover:text-ink-gray-6"
            >
              <LucideChevronRight class="h-3 w-3 transition-transform group-open:rotate-90" />
              {{ __('Raw') }}
            </summary>
            <pre
              class="mt-1.5 overflow-x-auto rounded-md bg-surface-gray-2 p-2.5 text-xs leading-relaxed text-ink-gray-7"
            >{{ prettyOutput(s) }}</pre>
          </details>
        </div>
      </div>
    </div>

    <div v-if="unattached.length" class="mt-2 border-t border-outline-gray-1 pt-3">
      <div class="mb-1.5 text-xs font-medium text-ink-gray-5">{{ __('Also recorded') }}</div>
      <div
        v-for="(l, i) in unattached"
        :key="i"
        class="py-0.5 text-xs"
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
 *
 * A bot step and a workflow node step carry their result differently -- a
 * workflow node puts fields like `sent`/`booked`/`records` at the top level
 * of its output, a bot step always nests the same shapes one level down
 * inside `result`, alongside the tool it called and what it was thinking.
 * summarise() and stepIcon() branch on node_type === 'Bot' to read the right
 * shape rather than stringifying whatever they find, which used to render
 * literally as "[object Object]" for every bot tool call.
 */
import { computed } from 'vue'
import { Badge, Button } from 'frappe-ui'
import { iconFor, iconForBotTool } from '@/components/Workflow/nodeIcons'
import { formatDate, timeAgo } from '@/utils'
import LucideArrowLeft from '~icons/lucide/arrow-left'
import LucideChevronRight from '~icons/lucide/chevron-right'
import LucideClock from '~icons/lucide/clock'
import LucideOctagonX from '~icons/lucide/octagon-x'
import LucideCheckCheck from '~icons/lucide/check-check'
import LucideBrainCircuit from '~icons/lucide/brain-circuit'

const props = defineProps({ run: { type: Object, required: true } })
defineEmits(['back'])

const statusTheme = (s) =>
  ({ Completed: 'green', Failed: 'red', Cancelled: 'gray', Expired: 'orange' })[
    s
  ] || 'blue'
const stepTheme = (s) =>
  ({ Success: 'green', Failed: 'red', Skipped: 'orange' })[s] || 'gray'

const BUBBLE_CLASSES = {
  Success: 'border-outline-green-2 bg-surface-green-1 text-ink-green-3',
  Failed: 'border-outline-red-2 bg-surface-red-1 text-ink-red-3',
  Skipped: 'border-outline-amber-2 bg-surface-amber-1 text-ink-amber-3',
}
const bubbleClasses = (status) =>
  BUBBLE_CLASSES[status] || 'border-outline-gray-2 bg-surface-gray-2 text-ink-gray-6'

const RESULT_CLASSES = { Failed: 'text-ink-red-6', Skipped: 'text-ink-amber-6' }
const resultClasses = (s) => RESULT_CLASSES[s.status] || 'text-ink-gray-7'

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

const isBot = (step) => step.node_type === 'Bot'

function parsed(step) {
  if (step._parsed !== undefined) return step._parsed
  try {
    step._parsed = JSON.parse(step.output || '{}')
  } catch {
    step._parsed = {}
  }
  return step._parsed
}

function hasRaw(step) {
  const out = parsed(step)
  return out && Object.keys(out).length > 0
}

function prettyOutput(step) {
  return JSON.stringify(parsed(step), null, 2)
}

/** The bot's own reasoning for this step, when it called a tool or reported
 * one worked -- not present on a Park step, which is the runtime's own
 * bookkeeping rather than something the model said. */
function thoughtFor(step) {
  if (!isBot(step)) return ''
  return parsed(step).thought || ''
}

function stepTitle(step) {
  if (!isBot(step)) return step.node_type
  const out = parsed(step)
  if (out.tool) return out.tool
  if (out.finished !== undefined) return __('Finished')
  return __('Decision')
}

function stepIcon(step) {
  if (!isBot(step)) return iconFor(step.node_type)
  const out = parsed(step)
  if (out.finished !== undefined) return LucideCheckCheck
  if (!out.tool) return LucideBrainCircuit
  return iconForBotTool(out.tool)
}

const WAITING_LINES = {
  Timer: __('Parked — retries automatically once the wait is over.'),
  Reply: __('Waiting for a reply.'),
  Approval: __('Waiting for approval.'),
}

/** One line worth reading, pulled out of the step's JSON. */
function summarise(step) {
  const out = parsed(step)
  return isBot(step) ? botSummary(out) : nodeSummary(out)
}

function nodeSummary(out) {
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

function botSummary(out) {
  if (out.finished !== undefined) return out.finished || __('Done.')
  if (out.waiting) return WAITING_LINES[out.waiting] || __('Waiting.')
  if (out.refused) return __('Refused: {0}', [out.refused])
  if (out.error) return __('Error: {0}', [out.error])
  if (out.would_call) return __('Would call {0} — dry run, nothing was sent.', [out.would_call])
  return resultSummary(out.result)
}

/** The result a tool call actually returned, once the tool and thought are
 * already shown above -- unwraps the same shapes nodeSummary() reads at the
 * top level, since a bot step nests them one level down inside `result`. */
function resultSummary(r) {
  if (r === undefined || r === null) return ''
  if (typeof r !== 'object') return String(r).slice(0, 200)
  if (r.sent === true) return r.to ? __('Sent to {0}.', [r.to]) : __('Sent.')
  if (r.sent === false || r.refused) return __('Refused: {0}', [r.refused])
  if (r.blocked) return __('Blocked: {0}', [r.skipped || r.blocked])
  if (r.booked) return __('Booked: {0}', [r.booked])
  if (r.event) return __('Booked.')
  if (r.updated) return __('Updated {0}.', [r.updated])
  if (r.created) return __('Created {0}.', [r.created])
  if (Array.isArray(r.records)) return __('{0} record(s) found.', [r.records.length])
  if (Array.isArray(r.slots)) return __('Offered {0} slot(s).', [r.slots.length])
  if (r.note) return String(r.note)
  return ''
}
</script>
