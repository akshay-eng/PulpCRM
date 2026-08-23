<template>
  <div
    class="relative w-[180px] rounded-xl border bg-surface-white px-3 py-2.5 shadow-sm transition"
    :class="[
      selected
        ? 'border-orange-400 ring-2 ring-orange-400/40'
        : 'border-outline-gray-2',
      data.enabled ? '' : 'opacity-50',
    ]"
  >
    <Handle
      v-for="pos in positions"
      :key="pos"
      :id="pos"
      type="source"
      :position="pos"
      class="!h-2 !w-2 !border !border-outline-gray-4 !bg-surface-base"
    />

    <div class="flex items-center gap-2">
      <div
        class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-gray-2"
      >
        <component :is="icon" class="h-4 w-4 text-ink-gray-7" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="truncate text-p-base font-medium text-ink-gray-8">
          {{ data.label }}
        </div>
        <div class="text-[10px] uppercase tracking-wide text-ink-gray-5">
          {{
            data.toolCount === 1
              ? __('1 tool')
              : __('{0} tools', [data.toolCount])
          }}
        </div>
      </div>
    </div>

    <!--
      A connector that needs a credential and has not got one is the single most
      common reason a bot silently does nothing. It says so on the node, not in
      a validation list somewhere else.
    -->
    <div
      v-if="data.needsCredential"
      class="mt-1.5 flex items-center gap-1 rounded bg-surface-amber-1 px-1.5 py-1 text-[11px] text-ink-amber-3"
    >
      <LucideTriangleAlert class="h-3 w-3 shrink-0" />
      <span class="truncate">{{
        __('{0} needed', [data.credentialLabel])
      }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { connectorIcon } from './connectorIcons'
import LucideTriangleAlert from '~icons/lucide/triangle-alert'

const props = defineProps({
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const positions = [Position.Top, Position.Right, Position.Bottom, Position.Left]
const icon = computed(() => connectorIcon(props.data.icon))
</script>
