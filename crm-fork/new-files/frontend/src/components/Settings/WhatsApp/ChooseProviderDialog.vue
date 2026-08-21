<template>
  <Dialog v-model="show" :options="{ title: __('Add a WhatsApp connection'), size: 'lg' }">
    <template #body-content>
      <p class="mb-4 text-p-sm text-ink-gray-6">
        {{ __('Two ways to reach WhatsApp. You can change this later.') }}
      </p>

      <button
        v-for="p in providers"
        :key="p.id"
        class="mb-3 flex w-full gap-3 rounded-lg border border-outline-gray-2 p-4 text-left transition hover:border-outline-gray-4 hover:bg-surface-gray-1"
        @click="choose(p.id)"
      >
        <component :is="p.icon" class="mt-0.5 h-5 w-5 shrink-0 text-ink-gray-7" />
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-base font-medium text-ink-gray-8">{{ p.label }}</span>
            <Badge :theme="p.theme" variant="subtle">{{ p.tag }}</Badge>
          </div>
          <div class="mt-1 text-p-sm text-ink-gray-6">{{ p.blurb }}</div>
          <ul class="mt-2 space-y-0.5 text-xs text-ink-gray-5">
            <li v-for="line in p.points" :key="line">• {{ line }}</li>
          </ul>
        </div>
      </button>
    </template>
  </Dialog>
</template>

<script setup>
import { Dialog, Badge } from 'frappe-ui'
import LucideBadgeCheck from '~icons/lucide/badge-check'
import LucideServer from '~icons/lucide/server'

const show = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['choose'])

const providers = [
  {
    id: 'meta',
    label: __('Meta Cloud API'),
    tag: __('Official'),
    theme: 'green',
    icon: LucideBadgeCheck,
    blurb: __('WhatsApp Business Platform, run by Meta.'),
    points: [
      __('Durable and supported; safe for production'),
      __('Needs a verified business and approved templates'),
      __('Free-form replies only inside a 24-hour window'),
      __('Cannot see messages you send from your own phone'),
    ],
  },
  {
    id: 'openwa',
    label: __('OpenWA'),
    tag: __('Self-hosted'),
    theme: 'orange',
    icon: LucideServer,
    blurb: __('A bridge you run yourself, on your own WhatsApp account.'),
    points: [
      __('No templates and no 24-hour window'),
      __('Sees replies you type on your own phone, so automation can stand down'),
      __('Set up in minutes — scan a QR code'),
      __('Unofficial; carries account-ban risk'),
    ],
  },
]

function choose(id) {
  show.value = false
  emit('choose', id)
}
</script>
