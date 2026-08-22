<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[{ label: __('AI Automation'), route: { name: 'Automation' } }]" />
    </template>
  </LayoutHeader>

  <div class="flex-1 overflow-y-auto px-6 py-8">
    <div class="mx-auto max-w-3xl">
      <h1 class="text-2xl font-semibold text-ink-gray-9">{{ __('AI Automation') }}</h1>
      <p class="mt-1 text-p-base text-ink-gray-6">
        {{ __('Two ways to get work done without doing it yourself.') }}
      </p>

      <div class="mt-7 grid gap-4 sm:grid-cols-2">
        <button
          v-for="card in cards"
          :key="card.name"
          class="group flex flex-col rounded-xl border border-outline-gray-2 bg-surface-white p-5 text-left transition hover:border-outline-gray-3 hover:shadow-sm"
          @click="$router.push({ name: card.route })"
        >
          <div class="flex items-center gap-3">
            <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-gray-2">
              <component :is="card.icon" class="h-5 w-5 text-ink-gray-7" />
            </div>
            <div>
              <div class="text-lg font-medium text-ink-gray-9">{{ card.title }}</div>
              <div class="text-p-sm text-ink-gray-5">{{ card.count }}</div>
            </div>
          </div>

          <p class="mt-3 text-p-base text-ink-gray-7">{{ card.blurb }}</p>

          <div class="mt-3 border-t border-outline-gray-1 pt-3 text-p-sm text-ink-gray-5">
            {{ card.example }}
          </div>

          <div class="mt-4 flex items-center gap-1 text-p-sm font-medium text-ink-gray-8">
            {{ card.cta }}
            <LucideArrowRight class="h-3.5 w-3.5 transition group-hover:translate-x-0.5" />
          </div>
        </button>
      </div>

      <!--
        The one place the difference is spelled out. Both boxes above sound
        appealing on their own; side by side they are still easy to confuse, and
        picking wrong means rebuilding.
      -->
      <div class="mt-6 rounded-lg bg-surface-gray-2 px-4 py-3 text-p-sm text-ink-gray-7">
        <b>{{ __('Not sure which?') }}</b>
        {{ __('If you can write the steps down in order, build a workflow — it does exactly that, every time. If the right next step depends on what the customer says, use a bot and let it decide.') }}
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * The landing page for the sidebar's "AI Automation" entry.
 *
 * Creation used to live in the Settings dialog, which was wrong twice over:
 * nobody looks in Settings to build something, and a canvas cannot live in a
 * modal. Settings keeps the credentials; this is where you make things.
 */
import LayoutHeader from '@/components/LayoutHeader.vue'
import { Breadcrumbs, call } from 'frappe-ui'
import { ref, computed, onMounted } from 'vue'
import LucideBot from '~icons/lucide/bot'
import LucideWorkflow from '~icons/lucide/workflow'
import LucideArrowRight from '~icons/lucide/arrow-right'

const bots = ref([])
const workflows = ref([])

const cards = computed(() => [
  {
    name: 'bots',
    route: 'Bots',
    icon: LucideBot,
    title: __('Bots'),
    count: countLabel(bots.value),
    blurb: __('Brief it, plug in what it is allowed to touch, and let it work out what to do.'),
    example: __('e.g. answer a new lead, find out what they want, book them in.'),
    cta: __('Open bots'),
  },
  {
    name: 'workflows',
    route: 'Workflows',
    icon: LucideWorkflow,
    title: __('Workflows'),
    count: countLabel(workflows.value),
    blurb: __('Draw the steps. It follows them in order, the same way every time.'),
    example: __('e.g. when a deal reaches Negotiation, assign it and email the customer.'),
    cta: __('Open workflows'),
  },
])

function countLabel(list) {
  if (!list.length) return __('None yet')
  const live = list.filter((x) => x.enabled).length
  return live
    ? __('{0} · {1} active', [__('{0} built', [list.length]), live])
    : __('{0} built · none active', [list.length])
}

onMounted(async () => {
  const [b, w] = await Promise.all([
    call('baton.api.bot.get_bots'),
    call('baton.api.workflow.get_workflows'),
  ])
  bots.value = b
  workflows.value = w
})
</script>
