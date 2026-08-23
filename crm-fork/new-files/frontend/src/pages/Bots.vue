<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          { label: __('AI Automations'), route: { name: 'Automation' } },
          { label: __('Bots'), route: { name: 'Bots' } },
        ]"
      />
    </template>
    <template #right-header>
      <Button
        variant="solid"
        :label="__('New bot')"
        :loading="creating"
        @click="create"
      >
        <template #prefix><TablerPlus class="h-4 w-4" /></template>
      </Button>
    </template>
  </LayoutHeader>

  <div class="flex-1 overflow-y-auto px-6 py-5">
    <div class="mx-auto max-w-3xl">
      <div v-if="loading" class="py-10 text-center text-p-base text-ink-gray-5">
        {{ __('Loading…') }}
      </div>

      <div
        v-else-if="!bots.length"
        class="flex flex-col items-center gap-2 rounded-xl border border-dashed border-outline-gray-2 py-14 text-ink-gray-5"
      >
        <TablerRobot class="h-8 w-8" />
        <div class="text-p-lg font-medium text-ink-gray-8">
          {{ __('No bots yet') }}
        </div>
        <div class="max-w-sm text-center text-p-base">
          {{
            __(
              'A bot is a brief plus the connectors it is allowed to use. It decides what to do; you decide what it can touch.',
            )
          }}
        </div>
        <Button
          class="mt-2"
          variant="solid"
          :label="__('Build one')"
          :loading="creating"
          @click="create"
        />
      </div>

      <div v-else class="flex flex-col gap-2">
        <div
          v-for="b in bots"
          :key="b.name"
          class="cursor-pointer rounded-lg border border-outline-gray-2 bg-surface-white px-4 py-3 transition hover:border-outline-gray-3"
          @click="open(b)"
        >
          <div class="flex items-center gap-3">
            <AutomationAvatar :identity="b.name || b.bot_name" kind="bot" />
            <div class="min-w-0 flex-1">
              <div class="truncate text-p-base font-medium text-ink-gray-8">
                {{ b.bot_name }}
              </div>
              <div class="truncate text-p-sm text-ink-gray-5">
                {{ b.description || __('No description') }}
              </div>
            </div>

            <Badge :theme="b.enabled ? 'green' : 'gray'" variant="subtle">
              {{ b.enabled ? __('Live') : __('Off') }}
            </Badge>
            <Dropdown
              :options="[
                {
                  label: __('Delete'),
                  icon: 'trash-2',
                  onClick: () => remove(b),
                },
              ]"
              @click.stop
            >
              <Button variant="ghost">
                <template #icon><TablerDots class="h-4 w-4" /></template>
              </Button>
            </Dropdown>
          </div>

          <div class="mt-2 flex flex-wrap items-center gap-1.5 pl-11">
            <span class="text-p-sm text-ink-gray-5">{{ triggerLabel(b) }}</span>
            <span v-if="b.connectors?.length" class="text-ink-gray-3">·</span>
            <Badge
              v-for="c in b.connectors"
              :key="c"
              theme="gray"
              variant="subtle"
            >
              {{ connectorLabel(c) }}
            </Badge>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import AutomationAvatar from '@/components/AutomationAvatar.vue'
import { Breadcrumbs, Button, Badge, Dropdown, call, toast } from 'frappe-ui'
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  IconRobot as TablerRobot,
  IconPlus as TablerPlus,
  IconDots as TablerDots,
} from '@tabler/icons-vue'

const router = useRouter()
const bots = ref([])
const catalog = ref([])
const loading = ref(true)
const creating = ref(false)

const connectorLabel = (id) =>
  catalog.value.find((c) => c.id === id)?.label || id

function triggerLabel(b) {
  if (!b.trigger_count) return __('Runs only when you start it')
  if (b.trigger_count === 1) return __('When {0}', [b.trigger_summary])
  return __('{0} triggers', [b.trigger_count])
}

async function load() {
  loading.value = true
  try {
    const [list, cat] = await Promise.all([
      call('baton.api.bot.get_bots'),
      call('baton.api.bot.get_connector_catalog'),
    ])
    bots.value = list
    catalog.value = cat
  } finally {
    loading.value = false
  }
}

const open = (b) => router.push({ name: 'Bot', params: { botId: b.name } })

/**
 * A new bot is saved with a starter brief and one connector already attached.
 * save_bot refuses an empty one -- correctly, since a bot with no instructions
 * and no connectors cannot do anything -- so handing someone that error as
 * their first experience would be daft.
 */
async function create() {
  creating.value = true
  try {
    const bot = await call('baton.api.bot.save_bot', {
      data: JSON.stringify({
        bot_name: __('Untitled bot'),
        instructions: __(
          'Describe what this bot is for and how it should behave.',
        ),
        channel: 'WhatsApp',
        connectors: [
          {
            connector: 'crm_leads',
            enabled: 1,
            position_x: 160,
            position_y: 120,
          },
        ],
        triggers: [],
      }),
    })
    open(bot)
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not create the bot'))
  } finally {
    creating.value = false
  }
}

async function remove(b) {
  if (
    !window.confirm(__('Delete “{0}”? Its run history goes too.', [b.bot_name]))
  )
    return
  try {
    await call('baton.api.bot.delete_bot', { name: b.name })
    toast.success(__('Deleted'))
    await load()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not delete'))
  }
}

onMounted(load)
</script>
