<template>
  <div
    class="relative w-[200px] rounded-lg border bg-surface-white px-3 py-2 shadow-sm transition"
    :class="selected ? 'border-orange-400 ring-2 ring-orange-200' : 'border-outline-gray-2 hover:border-outline-gray-3'"
  >
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

    <!-- A Condition forks, so it gets two labelled source handles. -->
    <template v-if="isCondition">
      <Handle id="true" type="source" :position="Position.Bottom" style="left: 32%"
        class="!h-2 !w-2 !border !border-green-500 !bg-white" />
      <Handle id="false" type="source" :position="Position.Bottom" style="left: 68%"
        class="!h-2 !w-2 !border !border-red-400 !bg-white" />
      <div class="pointer-events-none absolute -bottom-4 left-0 w-full text-[9px] text-ink-gray-5">
        <span class="absolute left-[22%]">{{ __('true') }}</span>
        <span class="absolute left-[62%]">{{ __('false') }}</span>
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
})

const isTrigger = computed(() => props.data.node_type === 'Trigger')
const isCondition = computed(() => props.data.node_type === 'Condition')
const icon = computed(() => iconFor(props.data.node_type))
</script>
