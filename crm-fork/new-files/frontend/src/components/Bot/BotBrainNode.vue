<template>
  <div
    class="relative w-[240px] rounded-2xl border-2 bg-surface-white px-4 py-3 shadow-sm transition"
    :class="
      selected
        ? 'border-orange-400 ring-4 ring-orange-400/30'
        : 'border-ink-gray-8'
    "
  >
    <!-- Connectors plug in from every side, so the brain has a handle on each. -->
    <Handle
      v-for="pos in positions"
      :key="pos"
      :id="pos"
      type="target"
      :position="pos"
      class="!h-2.5 !w-2.5 !border-2 !border-ink-gray-8 !bg-surface-base"
    />

    <div class="flex items-center gap-2.5">
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ink-gray-9"
      >
        <LucideBot class="h-5 w-5 text-white" />
      </div>
      <div class="min-w-0">
        <div class="text-[10px] uppercase tracking-wide text-ink-gray-5">
          {{ __('The bot') }}
        </div>
        <div class="truncate text-p-base font-medium text-ink-gray-9">
          {{ data.bot_name }}
        </div>
      </div>
    </div>

    <div class="mt-2 line-clamp-2 text-p-sm text-ink-gray-6">
      {{ data.instructions || __('No brief yet — click to write one.') }}
    </div>

    <div
      class="mt-2 flex flex-wrap items-center gap-1.5 border-t border-outline-gray-1 pt-2"
    >
      <span class="text-p-sm text-ink-gray-5">{{
        data.model || __('Default model')
      }}</span>
      <span
        v-if="data.guardrails"
        class="flex items-center gap-1 text-p-sm text-ink-gray-5"
      >
        <LucideShield class="h-3 w-3" /> {{ __('guarded') }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { Handle, Position } from '@vue-flow/core'
import LucideBot from '~icons/lucide/bot'
import LucideShield from '~icons/lucide/shield'

defineProps({
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const positions = [Position.Top, Position.Right, Position.Bottom, Position.Left]
</script>
