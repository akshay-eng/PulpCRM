<template>
  <div
    class="relative w-[214px] rounded-lg border bg-surface-white px-3 py-2 shadow-sm transition"
    :class="[
      selected ? 'border-orange-400 ring-2 ring-orange-200' : runBorder,
      data.runStatus ? '' : 'hover:border-outline-gray-3',
    ]"
  >
    <!-- When a run is open, tint by what this node actually did. -->
    <div
      v-if="data.runStatus"
      class="absolute -right-1.5 -top-1.5 rounded-full px-1.5 py-0.5 text-[9px] font-medium text-white"
      :class="runBadge"
    >
      {{ data.runStatus }}
    </div>
    <!-- Trigger nodes have nothing upstream, so no target handle. -->
    <Handle v-if="!isTrigger" type="target" :position="Position.Top" class="!h-2 !w-2 !border !border-gray-400 !bg-white" />

    <div class="flex items-center gap-2">
      <div class="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-surface-gray-2">
        <component :is="icon" class="h-3.5 w-3.5 text-ink-gray-7" />
      </div>
      <div class="min-w-0">
        <div class="text-[10px] uppercase tracking-wide text-ink-gray-5">
          {{ isTrigger ? __('Trigger') : __('Action') }}
        </div>
        <div class="truncate text-sm font-medium text-ink-gray-8">
          {{ data.label || data.node_type }}
        </div>
      </div>
    </div>

    <!--
      Anything that forks gets two labelled handles. Only Condition used to, so
      every other branch -- a reply that never came, a rejected approval -- was
      real at runtime and invisible on the canvas.
    -->
    <template v-if="branches">
      <Handle id="true" type="source" :position="Position.Bottom" style="left: 30%"
        class="!h-2 !w-2 !border !border-green-500 !bg-white" />
      <Handle id="false" type="source" :position="Position.Bottom" style="left: 70%"
        class="!h-2 !w-2 !border !border-red-400 !bg-white" />
      <div class="pointer-events-none absolute -bottom-4 left-0 flex w-full justify-between px-2 text-[9px]">
        <span class="text-green-600">{{ branches[0] }}</span>
        <span class="text-red-500">{{ branches[1] }}</span>
      </div>
    </template>
    <Handle v-else type="source" :position="Position.Bottom" class="!h-2 !w-2 !border !border-gray-400 !bg-white" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { iconFor } from './nodeIcons'

const props = defineProps({
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  branchLabels: { type: Object, default: () => ({}) },
})

const RUN_BORDER = {
  Success: 'border-green-400',
  Failed: 'border-red-400',
  Skipped: 'border-amber-400',
}
const RUN_BADGE = {
  Success: 'bg-green-500',
  Failed: 'bg-red-500',
  Skipped: 'bg-amber-500',
}
const runBorder = computed(
  () => RUN_BORDER[props.data.runStatus] || 'border-outline-gray-2',
)
const runBadge = computed(() => RUN_BADGE[props.data.runStatus] || 'bg-gray-400')

const isTrigger = computed(() => props.data.node_type === 'Trigger')
const branches = computed(() => props.branchLabels[props.data.node_type] || null)
const icon = computed(() => iconFor(props.data.node_type))
</script>
