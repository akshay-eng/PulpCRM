<template>
  <div>
    <div v-if="label" class="mb-1 text-p-sm text-ink-gray-7">{{ label }}</div>
    <Autocomplete
      :model-value="modelValue"
      :options="options"
      :placeholder="doctype ? __('Pick a field') : __('Set a trigger first')"
      @update:model-value="$emit('update:modelValue', $event?.value ?? $event)"
    />
    <!--
      A free-text box here saves cleanly, runs, and writes nothing when the name
      is misspelt. Without a trigger there is no record type to list, so say that
      rather than showing an empty box.
    -->
    <div v-if="!doctype" class="mt-1 text-p-sm text-amber-600">
      {{ __('Add a trigger so this knows which record it is working on.') }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { Autocomplete, call } from 'frappe-ui'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  doctype: { type: String, default: '' },
  label: { type: String, default: '' },
})
defineEmits(['update:modelValue'])

const fields = ref([])
const cache = new Map()

const options = computed(() =>
  fields.value.map((f) => ({
    label: f.label === f.field ? f.field : `${f.label} · ${f.field}`,
    value: f.field,
  })),
)

async function load(doctype) {
  if (!doctype) return (fields.value = [])
  if (cache.has(doctype)) return (fields.value = cache.get(doctype))
  const rows = await call('baton.api.workflow.get_fields', { doctype })
  cache.set(doctype, rows)
  fields.value = rows
}

watch(() => props.doctype, load, { immediate: true })

defineExpose({ fields })
</script>
