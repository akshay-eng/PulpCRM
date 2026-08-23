<template>
  <div class="flex flex-col gap-4">
    <FormControl
      v-model="bot.bot_name"
      type="text"
      :label="__('Name')"
      @blur="$emit('rename')"
    />

    <div>
      <div class="mb-1 text-p-sm text-ink-gray-7">
        {{ __('What it should do') }}
      </div>
      <textarea
        v-model="bot.instructions"
        rows="7"
        class="w-full resize-y rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5 text-p-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
        :placeholder="
          __(
            'You look after new leads. Message them, find out what they need, and book a call.',
          )
        "
      />
      <div class="mt-1 text-p-sm text-ink-gray-5">
        {{ __('Plain English. This is the brief, not a script.') }}
      </div>
    </div>

    <div>
      <div class="mb-1 flex items-center gap-1.5 text-p-sm text-ink-gray-7">
        <LucideShield class="h-3.5 w-3.5" />{{ __('Guardrails') }}
      </div>
      <textarea
        v-model="bot.guardrails"
        rows="5"
        class="w-full resize-y rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5 text-p-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
        :placeholder="
          __(
            'Never quote a price.\nNever promise a delivery date.\nStop if they ask to be left alone.',
          )
        "
      />
      <div class="mt-1 text-p-sm text-ink-gray-5">
        {{ __('One rule per line. These go into every decision it makes.') }}
      </div>
    </div>

    <div
      class="rounded-md bg-surface-gray-2 px-3 py-2 text-p-sm text-ink-gray-6"
    >
      {{
        __(
          'It can only ever use the connectors on the canvas — that limit is enforced in code, not by asking nicely.',
        )
      }}
    </div>

    <div class="border-t border-outline-gray-1 pt-3">
      <div class="mb-2 text-p-sm font-medium text-ink-gray-7">
        {{ __('Model') }}
      </div>
      <AICredentialPicker v-model="bot.ai_model" :label="__('Think with')" />
      <button
        class="mt-1.5 flex items-center gap-1 text-p-sm text-ink-gray-6 hover:text-ink-gray-8"
        @click="openSettings('AI models')"
      >
        <LucideSettings class="h-3 w-3" />
        {{ __('Manage browser credentials') }}
      </button>
    </div>

    <div class="grid grid-cols-2 gap-3 border-t border-outline-gray-1 pt-3">
      <div>
        <div class="mb-1 text-p-sm text-ink-gray-7">{{ __('Talks on') }}</div>
        <Select
          v-model="bot.channel"
          :options="[
            { label: 'WhatsApp', value: 'WhatsApp' },
            { label: 'Email', value: 'Email' },
            { label: __('Nothing'), value: 'None' },
          ]"
        />
      </div>
      <FormControl
        v-model.number="bot.max_steps"
        type="number"
        :label="__('Max steps')"
        :description="__('Stops runaway loops.')"
      />
    </div>
  </div>
</template>

<script setup>
import { FormControl, Select } from 'frappe-ui'
import { showSettings, activeSettingsPage } from '@/composables/settings'
import LucideShield from '~icons/lucide/shield'
import LucideSettings from '~icons/lucide/settings'
import AICredentialPicker from '@/components/AI/AICredentialPicker.vue'

defineProps({
  bot: { type: Object, required: true },
})
defineEmits(['rename'])

function openSettings(page) {
  activeSettingsPage.value = page
  showSettings.value = true
}
</script>
