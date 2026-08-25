<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          { label: __('AI Automations'), route: { name: 'Automation' } },
          { label: __('Workflows'), route: { name: 'Workflows' } },
        ]"
      />
      <span class="mx-1 text-ink-gray-4">/</span>
      <AutomationAvatar
        :identity="wf.name || route.params.workflowId"
        kind="workflow"
        size="sm"
        class="mr-1"
      />
      <input
        v-model="nameDraft"
        class="min-w-[8ch] rounded px-1 py-0.5 text-base font-medium text-ink-gray-8 hover:bg-surface-gray-2 focus:bg-surface-gray-2 focus:outline-none"
        :size="Math.max((nameDraft || '').length, 8)"
        :title="__('Rename')"
        @blur="rename"
        @keyup.enter="$event.target.blur()"
      />
      <span class="ml-1 text-p-sm text-ink-gray-5">
        {{ __('{0} steps', [wf.nodes.length]) }}
      </span>
    </template>
    <template #right-header>
      <Button
        variant="ghost"
        :disabled="!history.length"
        :title="__('Undo')"
        @click="undo"
      >
        <template #icon><TablerUndo class="h-4 w-4" /></template>
      </Button>
      <Button variant="ghost" :title="__('Tidy up the layout')" @click="tidy">
        <template #icon><TablerLayoutGrid class="h-4 w-4" /></template>
      </Button>
      <AICredentialPicker v-if="hasAINodes" v-model="credentialId" compact />
      <Button
        :label="__('Changes')"
        @click="
          router.push({
            name: 'Audit Trail',
            query: {
              doctype: 'Baton Workflow',
              name: wf.name || route.params.workflowId,
            },
          })
        "
      >
        <template #prefix><TablerListDetails class="h-4 w-4" /></template>
      </Button>
      <Button :label="__('See Runs')" @click="showRuns = true">
        <template #prefix><TablerHistory class="h-4 w-4" /></template>
      </Button>
      <Button :label="__('Test')" :loading="testing" @click="runTest">
        <template #prefix><TablerPlay class="h-4 w-4" /></template>
      </Button>
      <Button
        variant="solid"
        :loading="saving"
        :label="__('Save')"
        @click="save"
      />
      <Button
        :variant="wf.enabled ? 'subtle' : 'outline'"
        :label="wf.enabled ? __('Deactivate') : __('Activate')"
        @click="toggleEnabled"
      />
    </template>
  </LayoutHeader>

  <div class="flex flex-1 overflow-hidden">
    <NodePalette :catalog="catalog" @add="addNode($event)" />

    <div class="relative flex-1" @dragover.prevent @drop="onDrop">
      <div class="absolute left-4 top-4 z-10 w-[260px] space-y-2">
        <TriggerPanel
          :triggers="wf.triggers"
          :doctypes="doctypes"
          :events="events"
        />
      </div>

      <div
        v-if="problems.length"
        class="absolute bottom-4 left-4 z-10 max-w-[380px] rounded-lg border border-outline-gray-2 bg-surface-white p-3 shadow-sm"
      >
        <div class="mb-1 text-xs font-medium text-ink-gray-6">
          {{ __('Issues') }}
        </div>
        <div
          v-for="(p, i) in problems"
          :key="i"
          class="flex items-start gap-1.5 py-0.5 text-xs"
          :class="p.level === 'error' ? 'text-ink-red-4' : 'text-ink-amber-3'"
        >
          <span class="shrink-0">{{ p.level === 'error' ? '✕' : '!' }}</span>
          <span>
            <button
              v-if="p.node_id"
              class="underline"
              @click="selectedId = p.node_id"
            >
              {{ labelOf(p.node_id) }}
            </button>
            {{ p.message }}
          </span>
        </div>
      </div>

      <VueFlow
        v-model:nodes="flowNodes"
        v-model:edges="flowEdges"
        :default-viewport="{ zoom: 1 }"
        :min-zoom="0.3"
        :max-zoom="1.8"
        :connection-radius="30"
        :is-valid-connection="isValidConnection"
        fit-view-on-init
        class="pulp-flow h-full w-full"
        @node-click="onNodeClick"
        @node-drag-stop="onNodeDragStop"
        @connect="onConnect"
        @pane-click="closePanel"
      >
        <Background
          pattern-color="var(--outline-gray-2)"
          :gap="22"
          :size="1.4"
        />
        <Controls position="bottom-right" />
        <template #node-baton="props">
          <BatonNode
            :data="props.data"
            :selected="props.id === selectedId"
            :branch-labels="branchLabels"
          />
        </template>
        <template #edge-baton="props">
          <BatonEdge v-bind="props" @remove="removeEdge" />
        </template>
      </VueFlow>
    </div>

    <div
      v-if="selected"
      class="flex w-[340px] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-white"
    >
      <div
        class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3"
      >
        <div class="text-base font-medium text-ink-gray-8">
          {{ selected.label || selected.node_type }}
        </div>
        <button
          class="text-ink-gray-5 hover:text-ink-gray-8"
          @click="closePanel"
        >
          <TablerX class="h-4 w-4" />
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-4 py-3">
        <div
          v-if="isAINode(selected)"
          class="mb-4 rounded-md border border-outline-gray-2 bg-surface-gray-1 p-3"
        >
          <AICredentialPicker
            v-model="credentialId"
            :label="__('Run this workflow with')"
          />
        </div>
        <NodeConfigForm
          :node="selected"
          :schemas="schemas"
          :doctypes="doctypes"
          :agents="agents"
          :services="services"
          :availabilities="availabilities"
          :users="users"
          :error-schema="errorSchema"
          :trigger-doctype="selected.config?.for_doctype || triggerDoctype"
          :all-nodes="wf.nodes"
        />
        <Button
          v-if="selected.node_type !== 'Trigger'"
          class="mt-4 w-full"
          theme="red"
          variant="subtle"
          :label="__('Delete node')"
          @click="removeNode(selected)"
        />
      </div>
    </div>
  </div>

  <Dialog
    v-model="showRuns"
    :options="{ title: __('Workflow runs'), size: '3xl' }"
  >
    <template #body-content>
      <RunDetail v-if="openRun" :run="openRun" @back="closeRun" />

      <template v-else>
        <div
          v-if="!runs.length"
          class="py-6 text-center text-sm text-ink-gray-5"
        >
          {{ __('No runs yet. Hit Test to try it.') }}
        </div>
        <button
          v-for="r in runs"
          :key="r.name"
          class="flex w-full items-center gap-3 rounded-md px-2 py-2.5 text-left hover:bg-surface-gray-1"
          @click="openRunDetail(r.name)"
        >
          <Badge :theme="statusTheme(r.status)" variant="subtle" class="shrink-0">{{ r.status }}</Badge>
          <span class="truncate text-sm text-ink-gray-8">{{ r.reference_name || '—' }}</span>
          <span class="ml-auto shrink-0 text-xs text-ink-gray-5" :title="formatDate(r.creation)">
            {{ timeAgo(r.creation) }}
          </span>
          <LucideChevronRight class="h-4 w-4 shrink-0 text-ink-gray-4" />
        </button>
      </template>
    </template>
  </Dialog>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import AutomationAvatar from '@/components/AutomationAvatar.vue'
import BatonNode from '@/components/Workflow/BatonNode.vue'
import BatonEdge from '@/components/Workflow/BatonEdge.vue'
import RunDetail from '@/components/Workflow/RunDetail.vue'
import NodePalette from '@/components/Workflow/NodePalette.vue'
import NodeConfigForm from '@/components/Workflow/NodeConfigForm.vue'
import TriggerPanel from '@/components/Workflow/TriggerPanel.vue'
import { Breadcrumbs, Button, Badge, Dialog, call, toast } from 'frappe-ui'
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { formatDate, timeAgo } from '@/utils'
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
  IconListDetails as TablerListDetails,
  IconArrowBackUp as TablerUndo,
  IconLayoutGrid as TablerLayoutGrid,
} from '@tabler/icons-vue'
import AICredentialPicker from '@/components/AI/AICredentialPicker.vue'
import { useAICredentials } from '@/stores/aiCredentials'

const route = useRoute()
const router = useRouter()
const { screenToFlowCoordinate, fitView } = useVueFlow()

const wf = ref({
  workflow_name: '',
  kind: 'Workflow',
  enabled: 0,
  nodes: [],
  triggers: [],
})
const catalog = ref([])
const schemas = ref({})
const doctypes = ref([])
const agents = ref([])
const services = ref([])
const availabilities = ref([])
const users = ref([])
const errorSchema = ref([])
const branchLabels = ref({})
const events = ref([])
const runs = ref([])
const openRun = ref(null)
const problems = ref([])
const selectedId = ref(null)
const saving = ref(false)
const testing = ref(false)
const showRuns = ref(false)

const flowNodes = ref([])
const flowEdges = ref([])
const nameDraft = ref('')
const credentialContext = computed(
  () => `workflow:${wf.value.name || route.params.workflowId}`,
)
const { getSelection, setSelection, isReady, requestCredential } =
  useAICredentials()
const credentialId = ref(getSelection(credentialContext.value))
const isAINode = (node) =>
  ['AI Agent', 'AI Conversation'].includes(node?.node_type)
const hasAINodes = computed(() => wf.value.nodes.some(isAINode))

/**
 * workflow_name is the document name, so renaming has to go through
 * frappe.rename_doc to carry the run history across -- a field write would
 * leave every past run pointing at a workflow that no longer exists.
 */
async function rename() {
  const wanted = (nameDraft.value || '').trim()
  if (!wanted || wanted === wf.value.workflow_name) {
    nameDraft.value = wf.value.workflow_name
    return
  }
  try {
    const newName = await call('baton.api.workflow.rename_workflow', {
      name: wf.value.name,
      new_name: wanted,
    })
    router.replace({ name: 'Workflow', params: { workflowId: newName } })
    wf.value.name = newName
    wf.value.workflow_name = newName
    toast.success(__('Renamed'))
  } catch (e) {
    nameDraft.value = wf.value.workflow_name
    toast.error(e.messages?.[0] || __('Could not rename'))
  }
}

const selected = computed(
  () => wf.value.nodes.find((n) => n.node_id === selectedId.value) || null,
)
// The doctype the condition picker offers fields from.
const triggerDoctype = computed(
  () =>
    (wf.value.triggers || []).find((t) => t.trigger_doctype)?.trigger_doctype ||
    '',
)
const labelOf = (id) =>
  wf.value.nodes.find((n) => n.node_id === id)?.label || id

const statusTheme = (s) =>
  ({ Completed: 'green', Failed: 'red', Cancelled: 'gray', Expired: 'orange' })[
    s
  ] || 'blue'

/**
 * Give every node a place, and rescue graphs that have all of them in one.
 *
 * `position_y` is an Int server-side, and Frappe stores an unset Int as 0, not
 * NULL. So "never positioned" and "positioned at the top" are indistinguishable
 * after a round trip -- which is why every generated workflow used to render as
 * a single pile of cards stacked on the same spot. Rather than trusting a null
 * check that cannot work, detect the pile: if two nodes share a coordinate, the
 * layout is not a layout, and we compute a real one.
 */
const ROW = 140
const COL = 300

function layout(nodes) {
  const byId = Object.fromEntries(nodes.map((n) => [n.node_id, n]))
  const start = (nodes.find((n) => n.node_type === 'Trigger') || nodes[0])
    ?.node_id
  const placed = new Set()
  const queue = start ? [[start, 0, 0]] : []
  // Depth alone is not enough: two branches at the same depth would overlap, so
  // an occupied cell pushes the node one column right.
  const taken = new Set()

  while (queue.length) {
    const [id, depth, wanted] = queue.shift()
    const node = byId[id]
    if (!node || placed.has(id)) continue
    placed.add(id)

    let column = wanted
    while (taken.has(`${depth}:${column}`)) column += 1
    taken.add(`${depth}:${column}`)

    node.position_x = 420 + column * COL
    node.position_y = 80 + depth * ROW
    if (node.next_node) queue.push([node.next_node, depth + 1, column])
    if (node.next_node_alt)
      queue.push([node.next_node_alt, depth + 1, column + 1])
  }

  let orphan = 0
  for (const n of nodes) {
    if (!placed.has(n.node_id)) {
      n.position_x = 420 - COL
      n.position_y = 80 + orphan++ * ROW
    }
  }
}

function autoPosition() {
  const nodes = wf.value.nodes
  if (nodes.length < 2) {
    for (const n of nodes) {
      if (!n.position_x && !n.position_y) {
        n.position_x = 420
        n.position_y = 80
      }
    }
    return
  }
  const spots = new Set(
    nodes.map((n) => `${n.position_x || 0},${n.position_y || 0}`),
  )
  if (spots.size === nodes.length) return
  layout(nodes)
}

/** Explicit re-layout, for a graph someone has dragged into a tangle. */
function tidy() {
  snapshot()
  layout(wf.value.nodes)
  syncGraph()
  toast.success(__('Tidied up'))
}

function syncGraph() {
  autoPosition()
  const stepStatus = {}
  for (const s of openRun.value?.steps || []) stepStatus[s.node_id] = s.status

  flowNodes.value = wf.value.nodes.map((n) => ({
    id: n.node_id,
    type: 'baton',
    position: { x: n.position_x || 0, y: n.position_y || 0 },
    data: { ...n, runStatus: stepStatus[n.node_id] || null },
  }))

  const edges = []
  const base = { type: 'baton', markerEnd: MarkerType.ArrowClosed }
  for (const n of wf.value.nodes) {
    if (n.next_node) {
      edges.push({
        id: `${n.node_id}->${n.next_node}`,
        source: n.node_id,
        target: n.next_node,
        sourceHandle: branchLabels.value[n.node_type] ? 'true' : null,
        style: {
          stroke: branchLabels.value[n.node_type] ? '#16a34a' : '#94a3b8',
        },
        ...base,
      })
    }
    if (n.next_node_alt) {
      edges.push({
        id: `${n.node_id}->${n.next_node_alt}-alt`,
        source: n.node_id,
        target: n.next_node_alt,
        sourceHandle: 'false',
        style: { stroke: '#ef4444' },
        ...base,
      })
    }
  }
  flowEdges.value = edges
  validate()
}

/**
 * Undo, kept deliberately dumb: a stack of whole-graph snapshots.
 *
 * A drag-and-drop builder without undo means every mis-drop is repaired by
 * hand, and deleting the wrong node loses its config for good. Snapshots are
 * small (a graph is a few KB) and cannot desynchronise the way a command log
 * can.
 */
const history = ref([])
const HISTORY_LIMIT = 30

function snapshot() {
  history.value.push(
    JSON.stringify({ nodes: wf.value.nodes, triggers: wf.value.triggers }),
  )
  if (history.value.length > HISTORY_LIMIT) history.value.shift()
}

function undo() {
  const previous = history.value.pop()
  if (!previous) return
  const state = JSON.parse(previous)
  wf.value.nodes = state.nodes
  wf.value.triggers = state.triggers
  selectedId.value = null
  syncGraph()
}

function onKey(event) {
  const typing =
    /^(INPUT|TEXTAREA)$/.test(event.target?.tagName) ||
    event.target?.isContentEditable
  if (typing) return
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    undo()
  }
}

let validateTimer = null
function validate() {
  clearTimeout(validateTimer)
  validateTimer = setTimeout(async () => {
    try {
      problems.value = await call('baton.api.workflow.validate_workflow', {
        data: JSON.stringify({
          nodes: wf.value.nodes,
          triggers: wf.value.triggers,
          kind: wf.value.kind,
        }),
      })
    } catch {
      problems.value = []
    }
  }, 400)
}

watch(() => wf.value.nodes, validate, { deep: true })

// Opening the config panel narrows the canvas. Without a re-fit, whatever was
// on the right slides under the panel and stops being clickable.
watch(
  () => Boolean(selected.value),
  () =>
    nextTick(() =>
      setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 60),
    ),
)

function onNodeClick({ node }) {
  selectedId.value = node.id
}

function onNodeDragStop({ node }) {
  const n = wf.value.nodes.find((x) => x.node_id === node.id)
  if (n) {
    n.position_x = Math.round(node.position.x)
    n.position_y = Math.round(node.position.y)
  }
}

/**
 * A plain node has exactly one outgoing link, so a second edge from it would
 * silently overwrite the first. Only a Condition has two, and they are told
 * apart by handle.
 */
function isValidConnection({ source, target, sourceHandle }) {
  if (source === target) return false
  const src = wf.value.nodes.find((n) => n.node_id === source)
  const tgt = wf.value.nodes.find((n) => n.node_id === target)
  if (!src || !tgt) return false
  if (tgt.node_type === 'Trigger') return false
  if (!branchLabels.value[src.node_type] && sourceHandle === 'false')
    return false
  return true
}

function onConnect({ source, target, sourceHandle }) {
  snapshot()
  if (!isValidConnection({ source, target, sourceHandle })) return
  const n = wf.value.nodes.find((x) => x.node_id === source)
  if (sourceHandle === 'false') n.next_node_alt = target
  else n.next_node = target
  syncGraph()
}

function removeEdge({ source, sourceHandle }) {
  snapshot()
  const n = wf.value.nodes.find((x) => x.node_id === source)
  if (!n) return
  if (sourceHandle === 'false') n.next_node_alt = null
  else n.next_node = null
  syncGraph()
}

/** Drop from the palette: onto an edge inserts into it, onto blank canvas appends. */
function onDrop(event) {
  const raw = event.dataTransfer.getData('application/baton-node')
  if (!raw) return
  const action = JSON.parse(raw)
  const position = screenToFlowCoordinate({
    x: event.clientX,
    y: event.clientY,
  })

  const edgeEl = event.target.closest?.('.vue-flow__edge')
  const edgeId = edgeEl?.dataset?.id || edgeEl?.getAttribute?.('data-id')
  if (edgeId) {
    const edge = flowEdges.value.find((e) => e.id === edgeId)
    if (edge) return insertIntoEdge(action, edge, position)
  }
  addNode(action, position)
}

function newNode(action, position) {
  return {
    node_id: `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`,
    node_type: action.type,
    label: action.label,
    next_node: null,
    next_node_alt: null,
    // Palette entries carry a preset -- "Move the deal to a stage" arrives with
    // the doctype and field already chosen. Half the configuration of the most
    // common steps is simply not asked for.
    config: {
      ...(action.config || {}),
      ...(action.doctype ? { for_doctype: action.doctype } : {}),
    },
    save_as: null,
    position_x: Math.round(position?.x ?? 420),
    position_y: Math.round(position?.y ?? 80),
  }
}

/** The node a new step should hang off: the end of the chain, not the last row. */
function tailNode() {
  const byId = Object.fromEntries(wf.value.nodes.map((n) => [n.node_id, n]))
  // A selected node with a free output is what the user is looking at, so it is
  // the most likely thing they meant to continue from.
  const chosen = selected.value
  if (chosen && !chosen.next_node && chosen.node_type !== 'Trigger')
    return chosen

  let cur = (
    wf.value.nodes.find((n) => n.node_type === 'Trigger') || wf.value.nodes[0]
  )?.node_id
  const seen = new Set()
  while (cur && byId[cur] && !seen.has(cur)) {
    seen.add(cur)
    if (!byId[cur].next_node) return byId[cur]
    cur = byId[cur].next_node
  }
  return null
}

/**
 * Keep a dropped node off the one already there.
 *
 * Dropping near an existing node put the two cards on top of each other, which
 * is precisely the pile this builder is supposed to have stopped producing.
 */
function nudgeClear(node) {
  const W = 240
  const H = 90
  let guard = 0
  while (guard++ < 40) {
    const hit = wf.value.nodes.some(
      (n) =>
        n.node_id !== node.node_id &&
        Math.abs((n.position_x || 0) - node.position_x) < W &&
        Math.abs((n.position_y || 0) - node.position_y) < H,
    )
    if (!hit) return
    node.position_y += 60
  }
}

function addNode(action, position) {
  snapshot()
  const node = newNode(action, position)
  const from = tailNode()

  if (!position) {
    node.position_x = from?.position_x ?? 420
    node.position_y = (from?.position_y ?? 0) + 140
  }

  wf.value.nodes.push(node)
  nudgeClear(node)

  // Wire it on. A step dropped onto the canvas that nothing points at is a step
  // that will never run -- and the only clue was a warning in the Issues box.
  if (from) {
    if (branchLabels.value[from.node_type] && from.next_node)
      from.next_node_alt = node.node_id
    else from.next_node = node.node_id
  }

  selectedId.value = node.node_id
  syncGraph()
}

function insertIntoEdge(action, edge, position) {
  snapshot()
  const node = newNode(action, position)
  const src = wf.value.nodes.find((n) => n.node_id === edge.source)
  if (!src) return
  node.next_node = edge.target
  if (edge.sourceHandle === 'false') src.next_node_alt = node.node_id
  else src.next_node = node.node_id
  wf.value.nodes.push(node)
  nudgeClear(node)
  selectedId.value = node.node_id
  syncGraph()
}

function removeNode(node) {
  snapshot()
  wf.value.nodes.forEach((n) => {
    if (n.next_node === node.node_id) n.next_node = node.next_node
    if (n.next_node_alt === node.node_id) n.next_node_alt = node.next_node
    // fallback_node too. Leaving it dangling made the graph fail validation
    // with no way to repair it on the canvas -- an unsaveable workflow.
    if (n.fallback_node === node.node_id) {
      n.fallback_node = null
      if (n.on_error === 'Go to fallback') n.on_error = 'Fail run'
    }
  })
  wf.value.nodes = wf.value.nodes.filter((n) => n.node_id !== node.node_id)
  selectedId.value = null
  syncGraph()
}

async function load() {
  const [data, cat, meta, evts] = await Promise.all([
    call('baton.api.workflow.get_workflow', { name: route.params.workflowId }),
    call('baton.api.workflow.get_action_catalog'),
    call('baton.api.workflow.get_node_schemas'),
    call('baton.api.workflow.get_event_catalog'),
  ])
  data.triggers = data.triggers || []
  data.nodes.forEach((n) => (n.config = n.config || {}))
  wf.value = data
  nameDraft.value = data.workflow_name
  catalog.value = cat
  schemas.value = meta.schemas
  doctypes.value = meta.doctypes
  agents.value = meta.agents || []
  services.value = meta.services || []
  availabilities.value = meta.availabilities || []
  users.value = meta.users || []
  errorSchema.value = meta.error_schema || []
  branchLabels.value = meta.branch_labels || {}
  events.value = evts
  syncGraph()
}

async function save() {
  saving.value = true
  try {
    wf.value = await call('baton.api.workflow.save_workflow', {
      data: JSON.stringify({
        ...wf.value,
        name: wf.value.name || route.params.workflowId,
      }),
    })
    wf.value.triggers = wf.value.triggers || []
    wf.value.nodes.forEach((n) => (n.config = n.config || {}))
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

async function toggleEnabled() {
  if (!(await save())) return
  wf.value.enabled = await call('baton.api.workflow.set_enabled', {
    name: route.params.workflowId,
    enabled: wf.value.enabled ? 0 : 1,
  })
}

async function runTest() {
  if (!(await save())) return
  if (hasAINodes.value && !isReady(credentialId.value)) {
    toast.warning(__('Choose an AI key configured in this browser first.'))
    return
  }
  testing.value = true
  try {
    const res = await call('baton.api.workflow.test_run', {
      name: route.params.workflowId,
      credential: hasAINodes.value
        ? requestCredential(credentialId.value)
        : undefined,
    })
    if (!res.ok) return toast.warning(res.message)
    const r = res.run
    toast[r.status === 'Completed' ? 'success' : 'error'](
      __('Run {0} — {1} step(s)', [r.status, r.steps.length]),
    )
    await loadRuns()
    showRuns.value = true
  } finally {
    testing.value = false
  }
}

async function loadRuns() {
  runs.value = await call('baton.api.workflow.get_runs', {
    workflow: wf.value.name || route.params.workflowId,
  })
}

async function openRunDetail(name) {
  openRun.value = await call('baton.api.workflow.get_run', { name })
  // Tint the canvas by what actually happened, so a failure is visible on the
  // graph rather than only in the list.
  syncGraph()
}

function closeRun() {
  openRun.value = null
  syncGraph()
}

watch(showRuns, (v) => {
  if (v) loadRuns()
  else closeRun()
})
watch(credentialId, (value) => setSelection(credentialContext.value, value))
onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>
