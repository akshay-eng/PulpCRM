<template>
  <div class="flex flex-col gap-4">
    <div class="flex items-start gap-2.5">
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-gray-2"
      >
        <component
          :is="connectorIcon(spec.icon)"
          class="h-4 w-4 text-ink-gray-7"
        />
      </div>
      <div class="min-w-0">
        <div class="text-p-base font-medium text-ink-gray-8">
          {{ spec.label }}
        </div>
        <div class="text-p-sm text-ink-gray-5">{{ spec.description }}</div>
      </div>
    </div>

    <!-- Credential: chosen here, configured in Settings. -->
    <div
      v-if="spec.credential"
      class="rounded-lg border px-3 py-2.5"
      :class="
        spec.credential.configured
          ? 'border-outline-gray-2 bg-surface-white'
          : 'border-outline-amber-1 bg-surface-amber-1'
      "
    >
      <div class="flex items-center gap-2">
        <component
          :is="
            spec.credential.configured ? LucideCheckCircle : LucideTriangleAlert
          "
          class="h-4 w-4 shrink-0"
          :class="
            spec.credential.configured ? 'text-ink-green-2' : 'text-ink-amber-3'
          "
        />
        <div class="flex-1 text-p-base text-ink-gray-8">
          {{ spec.credential.label }}
        </div>
      </div>
      <div
        class="mt-1 text-p-sm"
        :class="
          spec.credential.configured ? 'text-ink-gray-5' : 'text-ink-amber-3'
        "
      >
        {{
          spec.credential.configured
            ? __('Connected. The bot uses it without ever seeing the key.')
            : __('Not set up yet, so this connector cannot do anything.')
        }}
      </div>
      <Button
        class="mt-2 w-full"
        :label="
          spec.credential.configured
            ? __('Change it in Settings')
            : __('Set it up in Settings')
        "
        @click="openSettings"
      >
        <template #suffix><LucideArrowUpRight class="h-3.5 w-3.5" /></template>
      </Button>
    </div>

    <!-- Per-bot options, e.g. which calendar, which URL. -->
    <div v-for="f in spec.config || []" :key="f.field">
      <div class="mb-1 text-p-sm text-ink-gray-7">
        {{ f.label }}<span v-if="f.required" class="text-red-500"> *</span>
      </div>
      <Select
        v-if="f.type === 'select'"
        :model-value="value(f)"
        :options="(f.options || []).map((o) => ({ label: o, value: o }))"
        @update:model-value="set(f, $event)"
      />
      <Select
        v-else-if="f.type === 'sender'"
        :model-value="value(f)"
        :options="[
          { label: __('The default mailbox'), value: '' },
          ...senders.map((a) => ({ label: a.email_id, value: a.email_id })),
        ]"
        @update:model-value="set(f, $event)"
      />
      <Select
        v-else-if="f.type === 'availability'"
        :model-value="value(f)"
        :options="[
          { label: __('Pick automatically'), value: '' },
          ...availabilities.map((a) => ({ label: a, value: a })),
        ]"
        @update:model-value="set(f, $event)"
      />
      <FormControl
        v-else-if="f.type === 'int'"
        type="number"
        :model-value="value(f)"
        @update:model-value="set(f, Number($event))"
      />
      <textarea
        v-else-if="f.type === 'textarea'"
        :value="value(f)"
        rows="4"
        spellcheck="false"
        :placeholder="f.placeholder"
        class="w-full resize-y rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5 text-p-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
        @input="set(f, $event.target.value)"
      />
      <FormControl
        v-else
        type="text"
        :model-value="value(f)"
        :placeholder="f.placeholder"
        @update:model-value="set(f, $event)"
      />
      <div v-if="f.help" class="mt-1 text-p-sm text-ink-gray-5">
        {{ f.help }}
      </div>
    </div>

    <!-- What attaching this actually grants. -->
    <div class="border-t border-outline-gray-1 pt-3">
      <div class="mb-1.5 text-p-sm font-medium text-ink-gray-7">
        {{ __('What this lets the bot do') }}
      </div>
      <div v-for="t in spec.tools" :key="t.name" class="flex items-start gap-2 py-1.5">
        <div class="min-w-0 flex-1">
          <div class="text-p-base text-ink-gray-8">{{ t.label || t.name }}</div>
          <div class="text-p-sm leading-snug text-ink-gray-5">
            {{ t.description }}
          </div>
        </div>
        <Switch
          class="mt-0.5 shrink-0"
          :model-value="toolEnabled(t.name)"
          @update:model-value="setToolEnabled(t.name, $event)"
        />
      </div>
    </div>

    <div
      class="flex items-center justify-between border-t border-outline-gray-1 pt-3"
    >
      <span class="text-p-sm text-ink-gray-7">{{ __('Enabled') }}</span>
      <Switch
        :model-value="Boolean(node.enabled)"
        @update:model-value="node.enabled = $event ? 1 : 0"
      />
    </div>

    <Button
      theme="red"
      variant="subtle"
      :label="__('Remove this connector')"
      @click="$emit('remove')"
    />
  </div>
</template>

<script setup>
import { Button, FormControl, Select, Switch } from 'frappe-ui'
import { showSettings, activeSettingsPage } from '@/composables/settings'
import { connectorIcon } from './connectorIcons'
import LucideCheckCircle from '~icons/lucide/check-circle'
import LucideTriangleAlert from '~icons/lucide/triangle-alert'
import LucideArrowUpRight from '~icons/lucide/arrow-up-right'

const props = defineProps({
  node: { type: Object, required: true },
  spec: { type: Object, required: true },
  availabilities: { type: Array, default: () => [] },
  senders: { type: Array, default: () => [] },
})
defineEmits(['remove'])

// WhatsApp is configured in CRM's own WhatsApp tab, not in Baton's settings.
const SETTINGS_PAGE = {
  whatsapp: 'WhatsApp',
  email: 'Accounts',
  calendar: 'Working hours',
  ai_model: 'AI models',
}

const value = (f) => props.node.config?.[f.field] ?? f.default ?? ''

function set(f, v) {
  if (!props.node.config) props.node.config = {}
  props.node.config[f.field] = v
}

function openSettings() {
  activeSettingsPage.value =
    SETTINGS_PAGE[props.spec.credential?.id] || 'AI models'
  showSettings.value = true
}

// Absent from disabled_tools means on -- matches the backend's own reading
// in bots/tools.py:execute(), so a connector saved before this UI existed
// still shows every tool switched on rather than guessing wrong.
const toolEnabled = (name) => !(props.node.disabled_tools || []).includes(name)

function setToolEnabled(name, enabled) {
  const off = new Set(props.node.disabled_tools || [])
  if (enabled) off.delete(name)
  else off.add(name)
  props.node.disabled_tools = [...off]
}
</script>
