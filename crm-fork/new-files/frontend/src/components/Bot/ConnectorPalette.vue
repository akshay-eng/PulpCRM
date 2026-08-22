<template>
  <div class="flex w-[236px] shrink-0 flex-col border-r border-outline-gray-2 bg-surface-white">
    <div class="border-b border-outline-gray-2 px-3 py-2.5">
      <div class="text-p-sm font-medium text-ink-gray-8">{{ __('Connectors') }}</div>
      <div class="mt-0.5 text-p-sm text-ink-gray-5">
        {{ __('Drag one onto the canvas to let the bot use it.') }}
      </div>
    </div>

    <div class="flex-1 overflow-y-auto px-2 py-2">
      <div v-for="group in groups" :key="group.name" class="mb-3">
        <div class="px-1 pb-1 text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">
          {{ group.name }}
        </div>
        <div
          v-for="c in group.items"
          :key="c.id"
          :draggable="!attached.includes(c.id)"
          class="group rounded-md px-2 py-1.5"
          :class="attached.includes(c.id)
            ? 'cursor-default opacity-40'
            : 'cursor-grab hover:bg-surface-gray-2 active:cursor-grabbing'"
          @dragstart="onDragStart($event, c)"
          @dblclick="!attached.includes(c.id) && $emit('add', c)"
        >
          <div class="flex items-center gap-2.5">
            <component :is="connectorIcon(c.icon)" class="h-4 w-4 shrink-0 text-ink-gray-6" />
            <span class="flex-1 truncate text-p-base text-ink-gray-8">{{ c.label }}</span>
            <LucideCheck v-if="attached.includes(c.id)" class="h-3.5 w-3.5 text-ink-gray-5" />
          </div>
          <!--
            Every item says what it does. Guessing from "Leads" whether that
            means read, write or both is exactly the guesswork a no-code tool
            exists to remove.
          -->
          <div class="pl-[26px] text-p-sm leading-snug text-ink-gray-5">{{ c.description }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { connectorIcon } from './connectorIcons'
import LucideCheck from '~icons/lucide/check'

const props = defineProps({
  catalog: { type: Array, default: () => [] },
  attached: { type: Array, default: () => [] },
})
defineEmits(['add'])

const groups = computed(() => {
  const out = []
  for (const c of props.catalog) {
    let group = out.find((g) => g.name === c.group)
    if (!group) out.push((group = { name: c.group, items: [] }))
    group.items.push(c)
  }
  return out
})

function onDragStart(event, connector) {
  if (props.attached.includes(connector.id)) return event.preventDefault()
  event.dataTransfer.setData('application/baton-connector', JSON.stringify(connector))
  event.dataTransfer.effectAllowed = 'move'
}
</script>
