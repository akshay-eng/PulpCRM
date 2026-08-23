<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          { label: __('AI Automations'), route: { name: 'Automation' } },
          { label: __('Bots'), route: { name: 'Bots' } },
        ]"
      />
      <span class="mx-1 text-ink-gray-4">/</span>
      <AutomationAvatar
        :identity="bot.name || route.params.botId"
        kind="bot"
        size="sm"
        class="mr-1"
      />
      <input
        v-model="nameDraft"
        class="min-w-[8ch] rounded px-1 py-0.5 text-p-base font-medium text-ink-gray-8 hover:bg-surface-gray-2 focus:bg-surface-gray-2 focus:outline-none"
        :size="Math.max((nameDraft || '').length, 8)"
        :title="__('Rename')"
        @blur="rename"
        @keyup.enter="$event.target.blur()"
      />
    </template>
    <template #right-header>
      <Button :label="__('Runs')" @click="showRuns = true">
        <template #prefix><TablerHistory class="h-4 w-4" /></template>
      </Button>
      <Button :label="__('Try it')" :loading="testing" @click="tryIt">
        <template #prefix><TablerPlay class="h-4 w-4" /></template>
      </Button>
      <Button
        variant="solid"
        :loading="saving"
        :label="__('Save')"
        @click="save"
      />
      <Button
        :variant="bot.enabled ? 'subtle' : 'outline'"
        :label="bot.enabled ? __('Switch off') : __('Switch on')"
        @click="toggle"
      />
    </template>
  </LayoutHeader>

  <div class="flex flex-1 overflow-hidden">
    <ConnectorPalette
      :catalog="catalog"
      :attached="attachedIds"
      @add="addConnector($event)"
    />

    <div class="relative flex-1" @dragover.prevent @drop="onDrop">
      <div class="absolute left-4 top-4 z-10 w-[268px] space-y-2">
        <TriggerPanel
          :triggers="bot.triggers"
          :doctypes="doctypes"
          :events="[]"
          allow-inbound
          :title="__('Wake it up when')"
        />
      </div>

      <div
        v-if="problems.length"
        class="absolute bottom-4 left-4 z-10 max-w-[380px] rounded-lg border border-outline-gray-2 bg-surface-white p-3 shadow-sm"
      >
        <div class="mb-1 text-p-sm font-medium text-ink-gray-6">
          {{ __('Before this can run') }}
        </div>
        <div
          v-for="(p, i) in problems"
          :key="i"
          class="flex items-start gap-1.5 py-0.5 text-p-sm"
          :class="p.level === 'error' ? 'text-ink-red-4' : 'text-ink-amber-3'"
        >
          <span class="shrink-0">{{ p.level === 'error' ? '✕' : '!' }}</span>
          <span>{{ p.message }}</span>
        </div>
      </div>

      <VueFlow
        v-model:nodes="flowNodes"
        v-model:edges="flowEdges"
        :min-zoom="0.3"
        :max-zoom="1.8"
        :nodes-connectable="false"
        fit-view-on-init
        class="pulp-flow h-full w-full"
        @node-click="onNodeClick"
        @node-drag-stop="onNodeDragStop"
        @pane-click="selectedId = null"
      >
        <Background
          pattern-color="var(--outline-gray-2)"
          :gap="22"
          :size="1.4"
        />
        <Controls position="bottom-right" />
        <template #node-brain="props">
          <BotBrainNode
            :data="props.data"
            :selected="props.id === selectedId"
          />
        </template>
        <template #node-connector="props">
          <ConnectorNode
            :data="props.data"
            :selected="props.id === selectedId"
          />
        </template>
      </VueFlow>
    </div>

    <div
      v-if="selectedId"
      class="flex w-[360px] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-white"
    >
      <div
        class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3"
      >
        <div class="text-p-base font-medium text-ink-gray-8">
          {{ selectedId === '__brain__' ? __('The brief') : __('Connector') }}
        </div>
        <button
          class="text-ink-gray-5 hover:text-ink-gray-8"
          @click="selectedId = null"
        >
          <TablerX class="h-4 w-4" />
        </button>
      </div>
      <div class="flex-1 overflow-y-auto px-4 py-4">
        <BotBrief
          v-if="selectedId === '__brain__'"
          :bot="bot"
          @rename="rename"
        />
        <ConnectorConfig
          v-else-if="selectedConnector"
          :node="selectedConnector"
          :spec="specOf(selectedConnector.connector)"
          :availabilities="availabilities"
          :senders="senders"
          @remove="removeConnector(selectedConnector)"
        />
      </div>
    </div>
  </div>

  <Dialog
    v-model="showRuns"
    :options="{ title: __('What this bot did'), size: '3xl' }"
  >
    <template #body-content>
      <RunDetail v-if="openRun" :run="openRun" @back="openRun = null" />
      <template v-else>
        <div
          v-if="!runs.length"
          class="py-6 text-center text-p-base text-ink-gray-5"
        >
          {{ __('It has not run yet. Hit “Try it”.') }}
        </div>
        <button
          v-for="r in runs"
          :key="r.name"
          class="flex w-full items-center gap-2 border-b border-outline-gray-1 py-2 text-left last:border-0 hover:bg-surface-gray-1"
          @click="openRunDetail(r.name)"
        >
          <Badge :theme="statusTheme(r.status)" variant="subtle">{{
            r.status
          }}</Badge>
          <span class="text-p-base text-ink-gray-7">{{
            r.reference_name || '—'
          }}</span>
          <span class="ml-auto text-p-sm text-ink-gray-5">{{
            r.creation
          }}</span>
          <TablerChevronRight class="h-4 w-4 text-ink-gray-4" />
        </button>
      </template>
    </template>
  </Dialog>
</template>

<script setup>
/**
 * The bot canvas: one brain in the middle, connectors plugged into it.
 *
 * Deliberately not the workflow canvas. There is no execution order here and no
 * edges to draw -- an edge exists because a connector is attached, full stop --
 * so connecting is dragging a connector on, and detaching is deleting it. Making
 * people wire edges by hand would imply an ordering the runtime does not have.
 */
import LayoutHeader from '@/components/LayoutHeader.vue'
import AutomationAvatar from '@/components/AutomationAvatar.vue'
import BotBrainNode from '@/components/Bot/BotBrainNode.vue'
import ConnectorNode from '@/components/Bot/ConnectorNode.vue'
import ConnectorPalette from '@/components/Bot/ConnectorPalette.vue'
import ConnectorConfig from '@/components/Bot/ConnectorConfig.vue'
import BotBrief from '@/components/Bot/BotBrief.vue'
import TriggerPanel from '@/components/Workflow/TriggerPanel.vue'
import RunDetail from '@/components/Workflow/RunDetail.vue'
import { Breadcrumbs, Button, Badge, Dialog, call, toast } from 'frappe-ui'
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, MarkerType, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import {
  IconX as TablerX,
  IconPlayerPlay as TablerPlay,
  IconHistory as TablerHistory,
  IconChevronRight as TablerChevronRight,
} from '@tabler/icons-vue'
import { useAICredentials } from '@/stores/aiCredentials'

const route = useRoute()
const router = useRouter()
const { screenToFlowCoordinate, fitView } = useVueFlow()

const bot = ref({ bot_name: '', connectors: [], triggers: [], enabled: 0 })
const catalog = ref([])
const doctypes = ref([])
const availabilities = ref([])
const senders = ref([])
const problems = ref([])
const runs = ref([])
const openRun = ref(null)
const selectedId = ref(null)
const nameDraft = ref('')
const saving = ref(false)
const testing = ref(false)
const showRuns = ref(false)
const flowNodes = ref([])
const flowEdges = ref([])
const { getSelection, setSelection, isReady, requestCredential } =
  useAICredentials()

const attachedIds = computed(() =>
  (bot.value.connectors || []).map((c) => c.connector),
)
const selectedConnector = computed(
  () =>
    (bot.value.connectors || []).find(
      (c) => c.connector === selectedId.value,
    ) || null,
)
const specOf = (id) => catalog.value.find((c) => c.id === id) || { tools: [] }
const statusTheme = (s) =>
  ({ Completed: 'green', Failed: 'red', Cancelled: 'gray', Expired: 'orange' })[
    s
  ] || 'blue'

/** Where a newly dropped connector goes when it lands on the brain itself. */
function freeSpot(index) {
  const ring = [
    [160, 90],
    [680, 90],
    [160, 430],
    [680, 430],
    [110, 260],
    [730, 260],
  ]
  return ring[index % ring.length]
}

function syncGraph() {
  const nodes = [
    {
      id: '__brain__',
      type: 'brain',
      position: {
        x: bot.value.position_x || 420,
        y: bot.value.position_y || 260,
      },
      data: {
        bot_name: bot.value.bot_name,
        instructions: bot.value.instructions,
        guardrails: bot.value.guardrails,
        model: bot.value.ai_model,
      },
    },
  ]
  const edges = []

  for (const c of bot.value.connectors || []) {
    const spec = specOf(c.connector)
    nodes.push({
      id: c.connector,
      type: 'connector',
      position: { x: c.position_x || 0, y: c.position_y || 0 },
      data: {
        label: c.label || spec.label || c.connector,
        icon: spec.icon,
        enabled: c.enabled,
        toolCount: (spec.tools || []).length,
        needsCredential: Boolean(
          spec.credential && !spec.credential.configured,
        ),
        credentialLabel: spec.credential?.label,
      },
    })
    edges.push({
      id: `${c.connector}->brain`,
      source: c.connector,
      target: '__brain__',
      type: 'default',
      style: { stroke: c.enabled ? '#94a3b8' : '#e2e8f0', strokeWidth: 1.5 },
      markerEnd: MarkerType.ArrowClosed,
    })
  }

  flowNodes.value = nodes
  flowEdges.value = edges
  validate()
}

let timer = null
function validate() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    try {
      problems.value = await call('baton.api.bot.validate_bot', {
        data: JSON.stringify(bot.value),
        browser_model: isReady(bot.value.ai_model)
          ? bot.value.ai_model
          : undefined,
      })
    } catch {
      problems.value = []
    }
  }, 400)
}

watch(bot, syncGraph, { deep: true })

/**
 * The panel is a flex sibling, so opening it makes the canvas narrower -- and
 * VueFlow keeps its viewport where it was, which pushes anything on the right
 * underneath the panel where it cannot be clicked. Re-fit whenever the panel
 * appears or disappears.
 */
watch(
  () => Boolean(selectedId.value),
  () =>
    nextTick(() =>
      setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 60),
    ),
)

function onNodeClick({ node }) {
  selectedId.value = node.id
}

function onNodeDragStop({ node }) {
  if (node.id === '__brain__') {
    bot.value.position_x = Math.round(node.position.x)
    bot.value.position_y = Math.round(node.position.y)
    return
  }
  const c = bot.value.connectors.find((x) => x.connector === node.id)
  if (c) {
    c.position_x = Math.round(node.position.x)
    c.position_y = Math.round(node.position.y)
  }
}

function onDrop(event) {
  const raw = event.dataTransfer.getData('application/baton-connector')
  if (!raw) return
  const spec = JSON.parse(raw)
  const at = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  addConnector(spec, at)
}

function addConnector(spec, at) {
  if (attachedIds.value.includes(spec.id)) {
    selectedId.value = spec.id
    return toast.info(__('{0} is already attached.', [spec.label]))
  }
  const [x, y] = freeSpot(bot.value.connectors.length)
  const config = {}
  for (const f of spec.config || []) {
    if (f.default !== undefined) config[f.field] = f.default
  }
  bot.value.connectors.push({
    connector: spec.id,
    label: spec.label,
    enabled: 1,
    config,
    position_x: Math.round(at?.x ?? x),
    position_y: Math.round(at?.y ?? y),
  })
  selectedId.value = spec.id
}

function removeConnector(c) {
  bot.value.connectors = bot.value.connectors.filter(
    (x) => x.connector !== c.connector,
  )
  selectedId.value = null
}

async function load() {
  const [data, cat, meta, mailboxes] = await Promise.all([
    call('baton.api.bot.get_bot', { name: route.params.botId }),
    call('baton.api.bot.get_connector_catalog'),
    call('baton.api.workflow.get_node_schemas'),
    call('baton.api.google.sending_accounts').catch(() => []),
  ])
  data.connectors = data.connectors || []
  data.triggers = data.triggers || []
  if (!data.ai_model) {
    data.ai_model = getSelection(`bot:${data.name || route.params.botId}`)
  }
  bot.value = data
  nameDraft.value = data.bot_name
  catalog.value = cat
  doctypes.value = meta.doctypes
  availabilities.value = meta.availabilities || []
  senders.value = mailboxes || []
  syncGraph()
}

async function save() {
  saving.value = true
  try {
    const saved = await call('baton.api.bot.save_bot', {
      data: JSON.stringify({
        ...bot.value,
        name: bot.value.name || route.params.botId,
      }),
    })
    saved.connectors = saved.connectors || []
    saved.triggers = saved.triggers || []
    bot.value = saved
    setSelection(`bot:${saved.name}`, saved.ai_model || '')
    syncGraph()
    toast.success(__('Saved'))
    return true
  } catch (e) {
    toast.error(e.messages?.[0] || e.message || __('Could not save'))
    return false
  } finally {
    saving.value = false
  }
}

async function rename() {
  const wanted = (nameDraft.value || '').trim()
  if (!wanted || wanted === bot.value.bot_name) {
    nameDraft.value = bot.value.bot_name
    return
  }
  try {
    const newName = await call('baton.api.bot.rename_bot', {
      name: bot.value.name,
      new_name: wanted,
    })
    router.replace({ name: 'Bot', params: { botId: newName } })
    bot.value.name = newName
    bot.value.bot_name = newName
  } catch (e) {
    nameDraft.value = bot.value.bot_name
    toast.error(e.messages?.[0] || __('Could not rename'))
  }
}

async function toggle() {
  if (!(await save())) return
  bot.value.enabled = await call('baton.api.bot.set_enabled', {
    name: bot.value.name,
    enabled: bot.value.enabled ? 0 : 1,
  })
}

async function tryIt() {
  if (!(await save())) return
  if (!isReady(bot.value.ai_model)) {
    toast.warning(__('Choose an AI key configured in this browser first.'))
    return
  }
  testing.value = true
  try {
    const res = await call('baton.api.bot.test_bot', {
      name: bot.value.name,
      credential: requestCredential(bot.value.ai_model),
    })
    if (!res.ok) return toast.warning(res.message)
    // Say what happened, not that something happened. A run that failed used to
    // toast "Dry run finished" and hide the reason inside the run dialog.
    if (res.run?.status === 'Failed')
      toast.error(res.run.error || __('The run failed'))
    else if (res.warning) toast.warning(res.warning)
    else toast.success(__('Dry run finished — nothing was actually sent.'))
    await loadRuns()
    openRun.value = res.run
    showRuns.value = true
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not run it'))
  } finally {
    testing.value = false
  }
}

async function loadRuns() {
  runs.value = await call('baton.api.bot.get_runs', { bot: bot.value.name })
}

async function openRunDetail(name) {
  openRun.value = await call('baton.api.bot.get_run', { name })
}

watch(showRuns, (v) => {
  if (v) loadRuns()
  else openRun.value = null
})
onMounted(load)
</script>
