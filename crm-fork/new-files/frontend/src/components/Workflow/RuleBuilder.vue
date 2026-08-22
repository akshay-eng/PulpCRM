<template>
  <div>
    <div v-if="!rules.length" class="mb-2 text-sm text-ink-gray-5">
      {{ __('Always continue. Add a rule to make it conditional.') }}
    </div>

    <div v-for="(r, i) in rules" :key="i" class="mb-2">
      <div class="mb-1 text-xs text-ink-gray-5">
        {{ i === 0 ? __('Continue when') : __('and') }}
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <FormControl
          v-model="r.field"
          type="select"
          :options="fieldOptions"
          class="min-w-[140px] flex-1"
        />
        <FormControl
          v-model="r.operator"
          type="select"
          :options="operators"
          class="min-w-[130px]"
        />
        <FormControl
          v-if="needsValue(r)"
          v-model="r.value"
          type="select"
          v-bind="valueBinding(r)"
          class="min-w-[120px] flex-1"
        />
        <button
          class="text-ink-gray-5 hover:text-red-600"
          :title="__('Remove rule')"
          @click="rules.splice(i, 1)"
        >
          <LucideX class="h-4 w-4" />
        </button>
      </div>
    </div>

    <Button :label="__('Add rule')" @click="add" />
  </div>
</template>

<script setup>
/**
 * Builds a Condition without anyone writing Python.
 *
 * The field list and the operator list both come from the server -- the fields
 * from the doctype the workflow triggers on, the operators from the engine's
 * own table -- so the picker can never offer something the engine cannot
 * evaluate.
 */
import { computed, ref, watch } from 'vue'
import { Button, FormControl, call } from 'frappe-ui'
import LucideX from '~icons/lucide/x'

const props = defineProps({
  rules: { type: Array, required: true },
  doctype: { type: String, default: '' },
})

const fields = ref([])
const operators = ref([])

const fieldOptions = computed(() =>
  fields.value.map((f) => ({ label: `${f.label} (${f.field})`, value: f.field })),
)

// "is set" and "is not set" take no value; offering an input would imply they do.
const needsValue = (r) => !['is set', 'is not set'].includes(r.operator)

function valueBinding(rule) {
  const meta = fields.value.find((f) => f.field === rule.field)
  if (meta?.options?.length) {
    return { type: 'select', options: meta.options }
  }
  return { type: 'text', placeholder: __('value') }
}

function add() {
  props.rules.push({
    field: fields.value[0]?.field || '',
    operator: 'is',
    value: '',
  })
}

async function load() {
  operators.value = await call('baton.api.workflow.get_operators')
  fields.value = props.doctype
    ? await call('baton.api.workflow.get_fields', { doctype: props.doctype })
    : []
}

watch(() => props.doctype, load, { immediate: true })
</script>
