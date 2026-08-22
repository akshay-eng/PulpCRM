<template>
  <div>
    <div v-if="label" class="mb-1 text-p-sm text-ink-gray-7">{{ label }}</div>

    <div v-if="!rows.length" class="rounded-md border border-dashed border-outline-gray-2 px-3 py-3 text-center text-p-sm text-ink-gray-5">
      {{ __('Nothing set yet.') }}
    </div>

    <div v-for="(row, i) in rows" :key="i" class="mb-1.5 flex items-center gap-1.5">
      <div class="flex-1">
        <Autocomplete
          v-if="doctype"
          :model-value="row.key"
          :options="fieldOptions"
          :placeholder="__('Field')"
          @update:model-value="setKey(i, $event?.value ?? $event)"
        />
        <input
          v-else
          :value="row.key"
          class="w-full rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1 text-p-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
          :placeholder="__('Name')"
          @input="setKey(i, $event.target.value)"
        />
      </div>
      <input
        :value="row.value"
        class="flex-1 rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1 text-p-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
        :placeholder="__('Value')"
        @input="setValue(i, $event.target.value)"
      />
      <button class="shrink-0 text-ink-gray-5 hover:text-red-600" @click="remove(i)">
        <LucideX class="h-3.5 w-3.5" />
      </button>
    </div>

    <button class="mt-1 flex items-center gap-1 text-p-sm text-ink-gray-6 hover:text-ink-gray-8"
            @click="add">
      <LucidePlus class="h-3 w-3" />{{ __('Add one') }}
    </button>
  </div>
</template>

<script setup>
/**
 * Replaces a JSON textarea. "Values" and "Body" were the last two places the
 * no-code builder asked people to hand-write JSON -- and a missing brace there
 * failed at save time with a parse error rather than at the field that caused it.
 *
 * Rows are the editing model; the bound object is rebuilt from them. Editing the
 * object directly would reorder keys and lose a half-typed name the moment it
 * was blank.
 */
import { ref, computed, watch } from 'vue'
import { Autocomplete, call } from 'frappe-ui'
import LucideX from '~icons/lucide/x'
import LucidePlus from '~icons/lucide/plus'

const props = defineProps({
  modelValue: { type: [Object, String], default: () => ({}) },
  doctype: { type: String, default: '' },
  label: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const rows = ref([])
const fields = ref([])
const cache = new Map()

const fieldOptions = computed(() =>
  fields.value.map((f) => ({
    label: f.label === f.field ? f.field : `${f.label} · ${f.field}`,
    value: f.field,
  })),
)

function fromValue(v) {
  let obj = v
  if (typeof v === 'string') {
    try { obj = JSON.parse(v || '{}') } catch (e) { obj = {} }
  }
  return Object.entries(obj || {}).map(([key, value]) => ({ key, value }))
}

watch(
  () => props.modelValue,
  (v) => {
    const next = fromValue(v)
    // Only adopt external changes; otherwise typing a value would rebuild the
    // rows underneath the cursor.
    if (JSON.stringify(next) !== JSON.stringify(rows.value.filter((r) => r.key))) {
      rows.value = next
    }
  },
  { immediate: true },
)

function commit() {
  const out = {}
  for (const r of rows.value) if (r.key) out[r.key] = r.value
  emit('update:modelValue', out)
}

const setKey = (i, v) => { rows.value[i].key = v; commit() }
const setValue = (i, v) => { rows.value[i].value = v; commit() }
const add = () => rows.value.push({ key: '', value: '' })
const remove = (i) => { rows.value.splice(i, 1); commit() }

async function loadFields(doctype) {
  if (!doctype) return (fields.value = [])
  if (cache.has(doctype)) return (fields.value = cache.get(doctype))
  const r = await call('baton.api.workflow.get_fields', { doctype })
  cache.set(doctype, r)
  fields.value = r
}
watch(() => props.doctype, loadFields, { immediate: true })
</script>
