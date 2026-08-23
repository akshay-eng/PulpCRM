<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[
        { label: __('AI Automation'), route: { name: 'Automation' } },
        { label: __('Bots'), route: { name: 'Bots' } },
      ]" />
      <span class="mx-1 text-ink-gray-4">/</span>
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
        <template #prefix><LucideHistory class="h-4 w-4" /></template>
      </Button>
      <Button :label="__('Try it')" :loading="testing" @click="tryIt">
        <template #prefix><LucidePlay class="h-4 w-4" /></template>
      </Button>
      <!--
        Work is saved as you go, so a refresh cannot throw it away. The label
        says which state we are in, because silent autosave leaves people
        wondering whether it happened.
      -->
      <span class="text-p-sm text-ink-gray-5">
        {{ saving ? __('Saving…') : dirty ? __('Unsaved') : __('Saved') }}
      </span>
      <Button variant="solid" :loading="saving" :label="__('Save')" @click="save" />
      <Button :variant="bot.enabled ? 'subtle' : 'outline'"
        :label="bot.enabled ? __('Switch off') : __('Switch on')" @click="toggle" />
    </template>
  </LayoutHeader>

  <div v-if="loadError"
    class="m-4 rounded-md border border-outline-red-2 bg-surface-red-1 px-4 py-3 text-p-base text-ink-red-3">
    {{ loadError }}
    <button class="ml-2 underline" @click="loadError = ''; load()">{{ __('Try again') }}</button>
  </div>

  <div v-else class="flex flex-1 overflow-hidden">
    <ConnectorPalette :catalog="catalog" :attached="attachedIds" @add="addConnector($event)" />

    <div class="relative flex-1" @dragover.prevent @drop="onDrop">
      <div class="absolute left-4 top-4 z-10 w-[268px] space-y-2">
        <TriggerPanel :triggers="bot.triggers" :doctypes="doctypes" :events="[]"
          allow-inbound :title="__('Wake it up when')" />
      </div>

      <div v-if="problems.length"
        class="absolute bottom-4 left-4 z-10 max-w-[380px] rounded-lg border border-outline-gray-2 bg-surface-white p-3 shadow-sm">
        <div class="mb-1 text-p-sm font-medium text-ink-gray-6">{{ __('Before this can run') }}</div>
        <div v-for="(p, i) in problems" :key="i"
          class="flex items-start gap-1.5 py-0.5 text-p-sm"
          :class="p.level === 'error' ? 'text-red-600' : 'text-amber-600'">
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
        class="h-full w-full"
        @node-click="onNodeClick"
        @node-drag-stop="onNodeDragStop"
        @pane-click="selectedId = null"
      >
        <Background pattern-color="#cbd5e1" :gap="22" :size="1.4" />
        <Controls position="bottom-right" />
        <template #node-brain="props">
          <BotBrainNode :data="props.data" :selected="props.id === selectedId" />
        </template>
        <template #node-connector="props">
          <ConnectorNode :data="props.data" :selected="props.id === selectedId" />
        </template>
      </VueFlow>
    </div>

    <div v-if="selectedId"
      class="flex w-[360px] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-white">
      <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3">
        <div class="text-p-base font-medium text-ink-gray-8">
          {{ selectedId === '__brain__' ? __('The brief') : __('Connector') }}
        </div>
        <button class="text-ink-gray-5 hover:text-ink-gray-8" @click="selectedId = null">
          <LucideX class="h-4 w-4" />
        </button>
      </div>
      <div class="flex-1 overflow-y-auto px-4 py-4">
        <BotBrief v-if="selectedId === '__brain__'" :bot="bot" :models="models" @rename="rename" />
        <ConnectorConfig v-else-if="selectedConnector"
          :node="selectedConnector"
          :spec="specOf(selectedConnector.connector)"
          :availabilities="availabilities"
          :senders="senders"
          :knowledge-bases="knowledgeBases"
          @remove="removeConnector(selectedConnector)" />
      </div>
    </div>
  </div>

  <Dialog v-model="showRuns" :options="{ title: __('What this bot did'), size: '3xl' }">
    <template #body-content>
      <RunDetail v-if="openRun" :run="openRun" @back="openRun = null" />
      <template v-else>
        <div v-if="!runs.length" class="py-6 text-center text-p-base text-ink-gray-5">
          {{ __('It has not run yet. Hit “Try it”.') }}
        </div>
        <button v-for="r in runs" :key="r.name"
          class="flex w-full items-center gap-2 border-b border-outline-gray-1 py-2 text-left last:border-0 hover:bg-surface-gray-1"
          @click="openRunDetail(r.name)">
          <Badge :theme="statusTheme(r.status)" variant="subtle">{{ r.status }}</Badge>
          <span class="text-p-base text-ink-gray-7">{{ r.reference_name || '—' }}</span>
          <span class="ml-auto text-p-sm text-ink-gray-5">{{ r.creation }}</span>
          <LucideChevronRight class="h-4 w-4 text-ink-gray-4" />
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
import BotBrainNode from '@/components/Bot/BotBrainNode.vue'
import ConnectorNode from '@/components/Bot/ConnectorNode.vue'
import ConnectorPalette from '@/components/Bot/ConnectorPalette.vue'
import ConnectorConfig from '@/components/Bot/ConnectorConfig.vue'
import BotBrief from '@/components/Bot/BotBrief.vue'
import TriggerPanel from '@/components/Workflow/TriggerPanel.vue'
import RunDetail from '@/components/Workflow/RunDetail.vue'
import { Breadcrumbs, Button, Badge, Dialog, call, toast } from 'frappe-ui'
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showSettings } from '@/composables/settings'
import { VueFlow, MarkerType, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import LucideX from '~icons/lucide/x'
import LucidePlay from '~icons/lucide/play'
import LucideHistory from '~icons/lucide/history'
import LucideChevronRight from '~icons/lucide/chevron-right'

const route = useRoute()
const router = useRouter()
const { screenToFlowCoordinate, fitView } = useVueFlow()

const bot = ref({ bot_name: '', connectors: [], triggers: [], enabled: 0 })
const catalog = ref([])
const models = ref([])
const doctypes = ref([])
const availabilities = ref([])
const senders = ref([])
const knowledgeBases = ref([])
const problems = ref([])
const runs = ref([])
const openRun = ref(null)
const selectedId = ref(null)
const nameDraft = ref('')
const saving = ref(false)
const dirty = ref(false)
const loadError = ref('')
// Set while server data is being applied, so writing the response back into
// `bot` does not look like an edit and retrigger the autosave forever.
let applying = false
let autosaveTimer = null
const testing = ref(false)
const showRuns = ref(false)
const flowNodes = ref([])
const flowEdges = ref([])

const attachedIds = computed(() => (bot.value.connectors || []).map((c) => c.connector))
const selectedConnector = computed(
  () => (bot.value.connectors || []).find((c) => c.connector === selectedId.value) || null,
)
const specOf = (id) => catalog.value.find((c) => c.id === id) || { tools: [] }
const statusTheme = (s) =>
  ({ Completed: 'green', Failed: 'red', Cancelled: 'gray', Expired: 'orange' })[s] || 'blue'

/** Where a newly dropped connector goes when it lands on the brain itself. */
function freeSpot(index) {
  const ring = [[160, 90], [680, 90], [160, 430], [680, 430], [110, 260], [730, 260]]
  return ring[index % ring.length]
}

function syncGraph() {
  const nodes = [{
    id: '__brain__',
    type: 'brain',
    position: { x: bot.value.position_x || 420, y: bot.value.position_y || 260 },
    data: {
      bot_name: bot.value.bot_name,
      instructions: bot.value.instructions,
      guardrails: bot.value.guardrails,
      model: bot.value.ai_model,
    },
  }]
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
        needsCredential: Boolean(spec.credential && !spec.credential.configured),
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
      })
    } catch (e) {
      problems.value = []
    }
  }, 400)
}

watch(bot, syncGraph, { deep: true })

/**
 * Autosave. A bot mid-build is usually invalid -- no instructions yet, a
 * connector pulled off to be put back -- so this saves as a draft, which
 * persists the work without pretending the bot is ready to run.
 */
watch(
  bot,
  () => {
    if (applying || !bot.value?.name) return
    dirty.value = true
    clearTimeout(autosaveTimer)
    autosaveTimer = setTimeout(() => persist({ draft: true }), 1200)
  },
  { deep: true },
)

/** Last line of defence: the tab is closing with work not yet written. */
function beforeUnload(e) {
  if (!dirty.value && !saving.value) return
  e.preventDefault()
  e.returnValue = ''
}

/**
 * The panel is a flex sibling, so opening it makes the canvas narrower -- and
 * VueFlow keeps its viewport where it was, which pushes anything on the right
 * underneath the panel where it cannot be clicked. Re-fit whenever the panel
 * appears or disappears.
 */
watch(
  () => Boolean(selectedId.value),
  () => nextTick(() => setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 60)),
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
    disabled_tools: [],
    position_x: Math.round(at?.x ?? x),
    position_y: Math.round(at?.y ?? y),
  })
  selectedId.value = spec.id
}

function removeConnector(c) {
  bot.value.connectors = bot.value.connectors.filter((x) => x.connector !== c.connector)
  selectedId.value = null
}

async function load() {
  try {
    const [data, cat, meta, mailboxes, bases] = await Promise.all([
      call('baton.api.bot.get_bot', { name: route.params.botId }),
      call('baton.api.bot.get_connector_catalog'),
      call('baton.api.workflow.get_node_schemas'),
      call('baton.api.google.sending_accounts').catch(() => []),
      // A Sales User may not manage knowledge bases; the canvas still loads.
      call('baton.api.kb.list_knowledge_bases').catch(() => []),
    ])
    data.connectors = data.connectors || []
    data.triggers = data.triggers || []
    // Applying loaded data is not an edit. Without this the arrival of the bot
    // marks it dirty and immediately autosaves it back.
    applying = true
    bot.value = data
    models.value = data.models || []
    nameDraft.value = data.bot_name
    catalog.value = cat
    doctypes.value = meta.doctypes
    availabilities.value = meta.availabilities || []
    senders.value = mailboxes || []
    knowledgeBases.value = bases || []
    await nextTick()
    applying = false
    dirty.value = false
    syncGraph()
  } catch (e) {
    // Silently leaving the default empty bot on screen looks exactly like a bot
    // that lost all its work, which is the worst possible way to fail here.
    applying = false
    loadError.value = e.messages?.[0] || e.message || __('Could not load this bot')
    toast.error(loadError.value)
  }
}

// The catalog's credential.configured flags are fetched once on load. A
// connector fixed in Settings -- opened as an overlay on this same page,
// not a navigation -- would otherwise keep showing "not connected" until a
// full reload, because nothing ever told this page to ask again.
async function refreshCatalog() {
  try {
    catalog.value = await call('baton.api.bot.get_connector_catalog')
  } catch (e) {
    // Silent: this is a background refresh of status badges, not a load the
    // user is waiting on.
  }
}

watch(showSettings, (open, wasOpen) => {
  if (!open && wasOpen) refreshCatalog()
})

async function persist({ draft = false } = {}) {
  clearTimeout(autosaveTimer)
  saving.value = true
  try {
    const saved = await call('baton.api.bot.save_bot', {
      data: JSON.stringify({ ...bot.value, name: bot.value.name || route.params.botId }),
      draft: draft ? 1 : 0,
    })
    saved.connectors = saved.connectors || []
    saved.triggers = saved.triggers || []
    applying = true
    bot.value = saved
    models.value = saved.models || []
    await nextTick()
    applying = false
    dirty.value = false
    syncGraph()
    if (!draft) toast.success(__('Saved'))
    return true
  } catch (e) {
    // A draft save failing is not worth a toast on every keystroke; the header
    // still says "Unsaved", and the explicit Save button reports properly.
    if (!draft) toast.error(e.messages?.[0] || e.message || __('Could not save'))
    return false
  } finally {
    saving.value = false
  }
}

const save = () => persist({ draft: false })

async function rename() {
  const wanted = (nameDraft.value || '').trim()
  if (!wanted || wanted === bot.value.bot_name) {
    nameDraft.value = bot.value.bot_name
    return
  }
  try {
    const newName = await call('baton.api.bot.rename_bot', {
      name: bot.value.name, new_name: wanted,
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
    name: bot.value.name, enabled: bot.value.enabled ? 0 : 1,
  })
}

async function tryIt() {
  if (!(await save())) return
  testing.value = true
  try {
    const res = await call('baton.api.bot.test_bot', { name: bot.value.name })
    if (!res.ok) return toast.warning(res.message)
    // Say what happened, not that something happened. A run that failed used to
    // toast "Dry run finished" and hide the reason inside the run dialog.
    if (res.run?.status === 'Failed') toast.error(res.run.error || __('The run failed'))
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
onMounted(() => {
  load()
  window.addEventListener('beforeunload', beforeUnload)
})

onBeforeUnmount(() => {
  clearTimeout(autosaveTimer)
  window.removeEventListener('beforeunload', beforeUnload)
  // Leaving the page with edits pending would lose them just as a refresh did.
  if (dirty.value) persist({ draft: true })
})
</script>
