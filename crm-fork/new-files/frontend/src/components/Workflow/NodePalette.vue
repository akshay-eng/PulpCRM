<template>
  <div class="flex w-[236px] shrink-0 flex-col border-r border-outline-gray-2 bg-surface-white">
    <div class="border-b border-outline-gray-2 px-3 py-2.5">
      <div class="text-p-sm font-medium text-ink-gray-8">{{ __('Steps') }}</div>
      <div class="mt-0.5 text-p-sm text-ink-gray-5">
        {{ __('Drag one onto the canvas, or onto a line to slot it in.') }}
      </div>
    </div>

    <div class="px-2 pb-1 pt-2">
      <div class="relative">
        <LucideSearch class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-gray-4" />
        <input
          v-model="query"
          class="w-full rounded-md border border-outline-gray-2 bg-surface-gray-1 py-1 pl-7 pr-2 text-p-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
          :placeholder="__('Search steps')"
        />
      </div>
    </div>

    <div class="flex-1 overflow-y-auto px-2 pb-2">
      <div v-if="!filtered.length" class="px-2 py-6 text-center text-p-sm text-ink-gray-5">
        {{ __('Nothing matches “{0}”.', [query]) }}
      </div>

      <div v-for="group in filtered" :key="group.group" class="mb-3">
        <div class="px-1 pb-1 text-[11px] font-medium uppercase tracking-wide text-ink-gray-4">
          {{ group.group }}
        </div>
        <div
          v-for="a in group.actions"
          :key="a.key"
          draggable="true"
          class="group cursor-grab rounded-md px-2 py-1.5 hover:bg-surface-gray-2 active:cursor-grabbing"
          @dragstart="onDragStart($event, a)"
          @dblclick="$emit('add', a)"
        >
          <div class="flex items-center gap-2.5">
            <component :is="iconFor(a)" class="h-4 w-4 shrink-0 text-ink-gray-6" />
            <span class="flex-1 truncate text-p-base text-ink-gray-8">{{ a.label }}</span>
          </div>
          <!--
            Every entry says what it does. "Check Reply" told you nothing until
            you dropped it, wired it and ran it -- which is a slow way to read
            documentation.
          -->
          <div v-if="a.help" class="pl-[26px] text-p-sm leading-snug text-ink-gray-5">
            {{ a.help }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { iconFor as iconForType, ICONS } from '@/components/Workflow/nodeIcons'
import LucideSearch from '~icons/lucide/search'

const props = defineProps({
  catalog: { type: Array, default: () => [] },
})
defineEmits(['add'])

const query = ref('')

// Several palette entries share a node type and differ by preset, so the type
// alone is not a key.
const keyed = computed(() =>
  props.catalog.map((g) => ({
    group: g.group,
    actions: g.actions.map((a, i) => ({ ...a, key: `${g.group}:${a.type}:${i}` })),
  })),
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return keyed.value
  return keyed.value
    .map((g) => ({
      group: g.group,
      actions: g.actions.filter((a) =>
        `${a.label} ${a.help || ''} ${g.group}`.toLowerCase().includes(q),
      ),
    }))
    .filter((g) => g.actions.length)
})

const iconFor = (a) => ICONS[a.icon] || iconForType(a.type)

function onDragStart(event, action) {
  event.dataTransfer.setData('application/baton-node', JSON.stringify(action))
  event.dataTransfer.effectAllowed = 'move'
}
</script>
