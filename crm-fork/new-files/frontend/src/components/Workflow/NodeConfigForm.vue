<template>
  <div>
    <FormControl
      v-model="node.label"
      type="text"
      :label="__('Label')"
      class="mb-3"
    />

    <div v-if="!fields.length" class="mb-3 text-p-sm text-ink-gray-5">
      {{ __('This node has nothing to configure.') }}
    </div>

    <div v-for="f in fields" :key="f.field" class="mb-3">
      <FormControl
        v-if="f.type === 'select'"
        v-model="node.config[f.field]"
        type="select"
        :label="__(f.label)"
        :options="f.options"
      />
      <FormControl
        v-else-if="f.type === 'agent'"
        v-model="node.config[f.field]"
        type="select"
        :label="__(f.label)"
        :options="agents"
      />
      <RuleBuilder
        v-else-if="f.type === 'rules'"
        :rules="ensureArray(f.field)"
        :doctype="triggerDoctype"
      />
      <FieldPicker
        v-else-if="f.type === 'field'"
        v-model="node.config[f.field]"
        :doctype="triggerDoctype"
        :label="__(f.label)"
      />
      <div v-else-if="f.type === 'fieldvalue'">
        <div class="mb-1 text-p-sm text-ink-gray-7">{{ __(f.label) }}</div>
        <!--
          A Select field has a fixed set of allowed values, and typing one that
          is not in it saves fine and then does nothing. When we know the
          options, offer them.
        -->
        <Autocomplete
          v-if="valueOptions.length"
          :model-value="node.config[f.field]"
          :options="valueOptions"
          :placeholder="__('Pick a value')"
          @update:model-value="node.config[f.field] = $event?.value ?? $event"
        />
        <FormControl
          v-else
          v-model="node.config[f.field]"
          type="text"
          :placeholder="f.placeholder"
        />
      </div>
      <KeyValueEditor
        v-else-if="f.type === 'keyvalue'"
        v-model="node.config[f.field]"
        :doctype="f.value_of ? node.config[f.value_of] : ''"
        :label="__(f.label)"
      />
      <FormControl
        v-else-if="f.type === 'user'"
        v-model="node.config[f.field]"
        type="select"
        :label="__(f.label)"
        :options="userOptions"
      />
      <FormControl
        v-else-if="f.type === 'node'"
        v-model="node[f.field]"
        type="select"
        :label="__(f.label)"
        :options="['', ...otherNodeIds]"
      />
      <FormControl
        v-else-if="f.type === 'service'"
        v-model="node.config[f.field]"
        type="select"
        :label="__(f.label)"
        :options="['', ...services]"
      />
      <FormControl
        v-else-if="f.type === 'availability'"
        v-model="node.config[f.field]"
        type="select"
        :label="__(f.label)"
        :options="['', ...availabilities]"
      />
      <FormControl
        v-else-if="f.type === 'doctype'"
        v-model="node.config[f.field]"
        type="select"
        :label="__(f.label)"
        :options="doctypes"
      />
      <FormControl
        v-else-if="f.type === 'int'"
        v-model.number="node.config[f.field]"
        type="number"
        :label="__(f.label)"
      />
      <FormControl
        v-else-if="f.type === 'check'"
        v-model="node.config[f.field]"
        type="checkbox"
        :label="__(f.label)"
      />
      <div v-else-if="f.type === 'textarea' || f.type === 'code'">
        <div class="mb-1 text-xs text-ink-gray-5">{{ __(f.label) }}</div>
        <textarea
          v-model="node.config[f.field]"
          :rows="f.type === 'code' ? 4 : 3"
          spellcheck="false"
          :placeholder="f.placeholder"
          :class="[
            'w-full rounded-md border border-outline-gray-2 bg-surface-gray-1 p-2 text-sm text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none',
            f.type === 'code' ? 'font-mono text-xs' : '',
          ]"
        ></textarea>
      </div>
      <FormControl
        v-else
        v-model="node.config[f.field]"
        type="text"
        :label="__(f.label)"
        :placeholder="f.placeholder"
      />

      <div v-if="f.help" class="mt-1 text-xs text-ink-gray-5">
        {{ __(f.help) }}
      </div>
      <div
        v-if="f.required && isBlank(node.config[f.field])"
        class="mt-1 text-xs text-ink-amber-3"
      >
        {{ __('Required') }}
      </div>
    </div>

    <details v-if="errorSchema.length" class="mt-4">
      <summary class="cursor-pointer text-p-sm text-ink-gray-5">
        {{ __('If it fails') }}
      </summary>
      <div class="mt-2">
        <div v-for="f in errorSchema" :key="f.field" class="mb-3">
          <template
            v-if="!f.depends_on || node[f.depends_on] === f.depends_value"
          >
            <FormControl
              v-if="f.type === 'select'"
              v-model="node[f.field]"
              type="select"
              :label="__(f.label)"
              :options="f.options"
            />
            <FormControl
              v-else-if="f.type === 'node'"
              v-model="node[f.field]"
              type="select"
              :label="__(f.label)"
              :options="['', ...otherNodeIds]"
            />
            <FormControl
              v-else
              v-model.number="node[f.field]"
              type="number"
              :label="__(f.label)"
            />
          </template>
        </div>
      </div>
    </details>

    <details class="mt-4">
      <summary class="cursor-pointer text-p-sm text-ink-gray-5">
        {{ __('Advanced') }}
      </summary>
      <div class="mt-2">
        <FormControl
          v-model="node.save_as"
          type="text"
          :label="__('Save result as')"
          class="mb-3"
          :placeholder="__('e.g. answer')"
        />
        <div class="text-xs text-ink-gray-5">
          {{ __('Later nodes can read it as vars.your_variable.') }}
        </div>
      </div>
      <div class="mt-3">
        <div class="mb-1 text-xs text-ink-gray-5">
          {{ __('Raw config (JSON)') }}
        </div>
        <textarea
          :value="rawText"
          rows="6"
          spellcheck="false"
          class="w-full rounded-md border border-outline-gray-2 bg-surface-gray-1 p-2 font-mono text-xs text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
          @input="onRawInput"
        ></textarea>
        <div v-if="rawError" class="mt-1 text-xs text-red-600">
          {{ rawError }}
        </div>
      </div>
    </details>
  </div>
</template>

<script setup>
/**
 * Forms are bound straight to `node.config`, which is a reactive object on the
 * node itself. There is deliberately no staging buffer: the old builder kept
 * the JSON in a separate ref and only committed it on save, so editing one node
 * and then clicking another silently threw the first edit away.
 *
 * The raw JSON box is a view onto the same object rather than a second source
 * of truth -- it writes through on every valid parse.
 */
import { computed, ref, watch } from 'vue'
import { Autocomplete, FormControl, call } from 'frappe-ui'
import RuleBuilder from '@/components/Workflow/RuleBuilder.vue'
import FieldPicker from '@/components/Workflow/FieldPicker.vue'
import KeyValueEditor from '@/components/Workflow/KeyValueEditor.vue'

const props = defineProps({
  node: { type: Object, required: true },
  schemas: { type: Object, default: () => ({}) },
  doctypes: { type: Array, default: () => [] },
  agents: { type: Array, default: () => [] },
  services: { type: Array, default: () => [] },
  availabilities: { type: Array, default: () => [] },
  users: { type: Array, default: () => [] },
  errorSchema: { type: Array, default: () => [] },
  triggerDoctype: { type: String, default: '' },
  allNodes: { type: Array, default: () => [] },
})

// Node ids are generated, so a picker showing them is a picker showing nothing.
const otherNodeIds = computed(() =>
  props.allNodes
    .filter((n) => n.node_id !== props.node.node_id)
    .map((n) => ({ label: n.label || n.node_id, value: n.node_id })),
)

const userOptions = computed(() => [
  { label: __('The record\u2019s owner'), value: '' },
  ...props.users.map((u) => ({ label: u.full_name || u.name, value: u.name })),
])

/**
 * When "New value" is being set on a Select field, offer that field's options.
 * Typing "qualified" into a status whose options are "Qualified" saves cleanly
 * and then quietly does nothing.
 */
const targetFields = ref([])
const fieldCache = new Map()

watch(
  () => props.triggerDoctype,
  async (doctype) => {
    if (!doctype) return (targetFields.value = [])
    if (fieldCache.has(doctype))
      return (targetFields.value = fieldCache.get(doctype))
    try {
      const rows = await call('baton.api.workflow.get_fields', { doctype })
      fieldCache.set(doctype, rows)
      targetFields.value = rows
    } catch (e) {
      targetFields.value = []
    }
  },
  { immediate: true },
)

const valueOptions = computed(() => {
  const chosen = props.node.config?.field
  if (!chosen) return []
  const meta = targetFields.value.find((f) => f.field === chosen)
  return (meta?.options || []).map((o) => ({ label: o, value: o }))
})

/** Rules live in config as an array; make sure one exists before binding. */
function ensureArray(field) {
  if (!Array.isArray(props.node.config[field])) props.node.config[field] = []
  return props.node.config[field]
}

const rawError = ref('')
const rawText = ref('{}')

const fields = computed(() => props.schemas[props.node.node_type] || [])

const isBlank = (v) => v === undefined || v === null || v === ''

// Apply declared defaults once, so a freshly dropped node is valid on arrival
// rather than showing a wall of "Required".
watch(
  () => props.node.node_id,
  () => {
    for (const f of fields.value) {
      if (f.default !== undefined && isBlank(props.node.config[f.field])) {
        props.node.config[f.field] = f.default
      }
    }
    rawText.value = JSON.stringify(props.node.config || {}, null, 2)
    rawError.value = ''
  },
  { immediate: true },
)

// Keep the raw box in step when the fields above it change it.
watch(
  () => props.node.config,
  (cfg) => {
    const next = JSON.stringify(cfg || {}, null, 2)
    if (next !== rawText.value && !rawError.value) rawText.value = next
  },
  { deep: true },
)

function onRawInput(event) {
  rawText.value = event.target.value
  try {
    const parsed = JSON.parse(rawText.value || '{}')
    rawError.value = ''
    // Mutate in place so the bindings above stay pointed at the same object.
    Object.keys(props.node.config).forEach((k) => delete props.node.config[k])
    Object.assign(props.node.config, parsed)
  } catch (e) {
    rawError.value = __('Invalid JSON') + ': ' + e.message
  }
}
</script>
