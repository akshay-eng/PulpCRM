<template>
  <div :class="compact ? 'flex items-center gap-1.5' : ''">
    <div v-if="!compact" class="mb-1 text-p-sm text-ink-gray-7">
      {{ label }}
    </div>
    <Select
      :model-value="modelValue"
      :options="pickerOptions"
      :placeholder="__('Choose a browser key')"
      :class="compact ? 'w-56' : 'w-full'"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <Button
      variant="ghost"
      :label="compact ? '' : __('Configure keys')"
      :title="__('Configure browser keys')"
      @click="openSettings"
    >
      <template #prefix><LucideKeyRound class="h-3.5 w-3.5" /></template>
    </Button>
    <div
      v-if="!compact && modelValue && !isReady(modelValue)"
      class="mt-1 text-p-sm text-ink-amber-3"
    >
      {{ __('This credential has no key in this browser.') }}
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Button, Select } from 'frappe-ui'
import { useAICredentials } from '@/stores/aiCredentials'
import { showSettings, activeSettingsPage } from '@/composables/settings'
import LucideKeyRound from '~icons/lucide/key-round'

defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, default: () => __('AI credential') },
  compact: { type: Boolean, default: false },
})
defineEmits(['update:modelValue'])

const { options, isReady } = useAICredentials()
const pickerOptions = computed(() => [
  { label: __('No browser key selected'), value: '' },
  ...options.value,
])

function openSettings() {
  activeSettingsPage.value = 'AI models'
  showSettings.value = true
}
</script>
