<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          { label: __('Workflows'), route: { name: 'Workflows' } },
          { label: wf.workflow_name || __('Untitled'), route: {} },
        ]"
      />
      <span class="ml-1 text-sm text-ink-gray-5">({{ wf.nodes.length }})</span>
    </template>
    <template #right-header>
      <Button :label="__('Add a Node')" @click="openPalette(null)">
        <template #prefix><LucidePlus class="h-4 w-4" /></template>
      </Button>
      <Button :label="__('See Runs')" @click="showRuns = true">
        <template #prefix><LucideHistory class="h-4 w-4" /></template>
      </Button>
      <Button :label="__('Test')" :loading="testing" @click="runTest">
        <template #prefix><LucidePlay class="h-4 w-4" /></template>
      </Button>
      <Button
        :variant="wf.enabled ? 'subtle' : 'solid'"
        :label="wf.enabled ? __('Deactivate') : __('Activate')"
        @click="toggleEnabled"
      />
    </template>
  </LayoutHeader>

  <div class="flex flex-1 overflow-hidden">
    <div class="relative flex-1">
      <div class="absolute left-4 top-4 z-10">
        <Badge :theme="wf.enabled ? 'green' : 'gray'" variant="subtle">
          {{ wf.enabled ? __('Active') : __('Inactive') }}
        </Badge>
      </div>

      <VueFlow
        v-model:nodes="flowNodes"
        v-model:edges="flowEdges"
        :default-viewport="{ zoom: 1 }"
        :min-zoom="0.3"
        :max-zoom="1.8"
        :connection-radius="30"
        fit-view-on-init
        class="h-full w-full"
        @node-click="onNodeClick"
        @node-drag-stop="onNodeDragStop"
        @connect="onConnect"
        @pane-click="closePanel"
      >
        <Background pattern-color="#cbd5e1" :gap="22" :size="1.4" />
        <Controls position="bottom-left" />
        <template #node-baton="props">
          <BatonNode :data="props.data" :selected="props.id === selectedId" />
        </template>
      </VueFlow>
    </div>

    <div
      v-if="paletteOpen || selected"
      class="flex w-[340px] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-white"
    >
      <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3">
        <div class="text-base font-medium text-ink-gray-8">
          {{ paletteOpen ? __('Select Action') : selected.label || selected.node_type }}
        </div>
        <button class="text-ink-gray-5 hover:text-ink-gray-8" @click="closePanel">
          <LucideX class="h-4 w-4" />
        </button>
      </div>

      <div v-if="paletteOpen" class="flex-1 overflow-y-auto px-2 py-3">
        <div v-for="group in catalog" :key="group.group" class="mb-4">
          <div class="px-2 pb-1 text-xs font-medium text-ink-gray-5">{{ group.group }}</div>
          <button
            v-for="a in group.actions"
            :key="a.type"
            class="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-ink-gray-8 hover:bg-surface-gray-2"
            @click="addNode(a)"
          >
            <component :is="iconFor(a.type)" class="h-4 w-4 text-ink-gray-6" />
            {{ a.label }}
          </button>
        </div>
      </div>

      <div v-else class="flex-1 overflow-y-auto px-4 py-3">
        <FormControl v-model="selected.label" type="text" :label="__('Label')" class="mb-3" />
        <div class="mb-1 text-xs font-medium text-ink-gray-5">{{ __('Configuration (JSON)') }}</div>
        <textarea
          v-model="configText"
          rows="10"
          spellcheck="false"
          class="w-full rounded-md border border-outline-gray-2 bg-surface-gray-1 p-2 font-mono text-xs text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
          :placeholder="placeholderFor(selected.node_type)"
        ></textarea>
        <div v-if="configError" class="mt-1 text-xs text-red-600">{{ configError }}</div>
        <div class="mt-2 text-xs text-ink-gray-5">{{ hintFor(selected.node_type) }}</div>
        <Button
          class="mt-4 w-full"
          theme="red"
          variant="subtle"
          :label="__('Delete node')"
          @click="removeNode(selected)"
        />
      </div>

      <div class="border-t border-outline-gray-2 px-4 py-3">
        <Button variant="solid" class="w-full" :loading="saving" :label="__('Save')" @click="save" />
      </div>
    </div>
  </div>

  <Dialog v-model="showRuns" :options="{ title: __('Workflow runs'), size: '3xl' }">
    <template #body-content>
      <div v-if="!runs.length" class="py-6 text-center text-sm text-ink-gray-5">
        {{ __('No runs yet. Hit Test to try it.') }}
      </div>
      <div v-for="r in runs" :key="r.name" class="border-b border-outline-gray-1 py-2 last:border-0">
        <div class="flex items-center gap-2">
          <Badge
            :theme="r.status === 'Completed' ? 'green' : r.status === 'Failed' ? 'red' : 'orange'"
            variant="subtle"
          >{{ r.status }}</Badge>
          <span class="text-sm text-ink-gray-7">{{ r.reference_name || '—' }}</span>
          <span class="ml-auto text-xs text-ink-gray-5">{{ r.creation }}</span>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import BatonNode from '@/components/Workflow/BatonNode.vue'
import { iconFor } from '@/components/Workflow/nodeIcons'
import { Breadcrumbs, Button, Badge, Dialog, FormControl, call, toast } from 'frappe-ui'
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { VueFlow, MarkerType } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'
import LucidePlay from '~icons/lucide/play'
import LucideHistory from '~icons/lucide/history'

const route = useRoute()
const wf = ref({ workflow_name: '', enabled: 0, nodes: [] })
const catalog = ref([])
const runs = ref([])
const selectedId = ref(null)
const paletteOpen = ref(false)
const insertAfter = ref(null)
const saving = ref(false)
const testing = ref(false)
const showRuns = ref(false)
const configText = ref('{}')
const configError = ref('')

const flowNodes = ref([])
const flowEdges = ref([])

const PLACEHOLDERS = {
  Condition: '{\n  "expression": "doc.status == \'Open\'"\n}',
  'Update Field': '{\n  "field": "status",\n  "value": "Contacted"\n}',
  'Send WhatsApp': '{\n  "to": "{{ doc.mobile_no }}",\n  "message": "Hi {{ doc.lead_name }}",\n  "author": "ai"\n}',
  'Send Email': '{\n  "to": "{{ doc.email }}",\n  "subject": "Hello",\n  "message": "..."\n}',
  'AI Agent': '{\n  "prompt": "Summarise this lead: {{ doc.lead_name }}"\n}',
}
const placeholderFor = (t) => PLACEHOLDERS[t] || '{}'
const HINTS = {
  Condition: 'Python expression over `doc`. The true handle runs when it matches.',
  'Update Field': 'Writes one field on the triggering record.',
  'Send WhatsApp': 'author: ai marks it agent-written, so a human reply cancels queued follow-ups.',
}
const hintFor = (t) => HINTS[t] || 'Values support {{ doc.fieldname }}.'

const selected = computed(() => wf.value.nodes.find((n) => n.node_id === selectedId.value) || null)

/** Lay out any node that has never been positioned, following next_node. */
function autoPosition() {
  const byId = Object.fromEntries(wf.value.nodes.map((n) => [n.node_id, n]))
  const seen = new Set()
  let cur = (wf.value.nodes.find((n) => n.node_type === 'Trigger') || wf.value.nodes[0])?.node_id
  let row = 0
  while (cur && byId[cur] && !seen.has(cur)) {
    seen.add(cur)
    const n = byId[cur]
    if (!n.position_x && !n.position_y) {
      n.position_x = 400
      n.position_y = row * 130 + 60
    }
    row += 1
    cur = n.next_node
  }
  wf.value.nodes.forEach((n) => {
    if (!seen.has(n.node_id) && !n.position_x && !n.position_y) {
      n.position_x = 700
      n.position_y = row++ * 130 + 60
    }
  })
}

function syncGraph() {
  autoPosition()
  flowNodes.value = wf.value.nodes.map((n) => ({
    id: n.node_id,
    type: 'baton',
    position: { x: n.position_x || 0, y: n.position_y || 0 },
    data: n,
  }))

  const edges = []
  const edgeStyle = { type: 'smoothstep', markerEnd: MarkerType.ArrowClosed }
  for (const n of wf.value.nodes) {
    if (n.next_node) {
      edges.push({
        id: `${n.node_id}->${n.next_node}`,
        source: n.node_id,
        target: n.next_node,
        sourceHandle: n.node_type === 'Condition' ? 'true' : null,
        style: { stroke: n.node_type === 'Condition' ? '#16a34a' : '#94a3b8' },
        ...edgeStyle,
      })
    }
    if (n.next_node_alt) {
      edges.push({
        id: `${n.node_id}->${n.next_node_alt}-alt`,
        source: n.node_id,
        target: n.next_node_alt,
        sourceHandle: 'false',
        style: { stroke: '#ef4444' },
        ...edgeStyle,
      })
    }
  }
  flowEdges.value = edges
}

watch(selected, (n) => {
  configText.value = n ? JSON.stringify(n.config || {}, null, 2) : '{}'
  configError.value = ''
})

function onNodeClick({ node }) {
  paletteOpen.value = false
  selectedId.value = node.id
}
function onNodeDragStop({ node }) {
  const n = wf.value.nodes.find((x) => x.node_id === node.id)
  if (n) {
    n.position_x = Math.round(node.position.x)
    n.position_y = Math.round(node.position.y)
  }
}
/** Dragging a handle onto another node rewires the graph. */
function onConnect({ source, target, sourceHandle }) {
  const n = wf.value.nodes.find((x) => x.node_id === source)
  if (!n || source === target) return
  if (sourceHandle === 'false') n.next_node_alt = target
  else n.next_node = target
  syncGraph()
}

function openPalette(afterId) {
  insertAfter.value = afterId
  selectedId.value = null
  paletteOpen.value = true
}
function closePanel() {
  paletteOpen.value = false
  selectedId.value = null
}

function addNode(action) {
  const id = `n${Date.now().toString(36)}`
  const last = wf.value.nodes[wf.value.nodes.length - 1]
  const node = {
    node_id: id,
    node_type: action.type,
    label: action.label,
    next_node: null,
    next_node_alt: null,
    config: {},
    position_x: (last?.position_x || 400),
    position_y: (last?.position_y || 0) + 130,
  }
  const afterId = insertAfter.value || last?.node_id
  const prev = wf.value.nodes.find((n) => n.node_id === afterId)
  if (prev) {
    node.next_node = prev.next_node || null
    prev.next_node = id
  }
  wf.value.nodes.push(node)
  paletteOpen.value = false
  selectedId.value = id
  syncGraph()
}

function removeNode(node) {
  wf.value.nodes.forEach((n) => {
    if (n.next_node === node.node_id) n.next_node = node.next_node
    if (n.next_node_alt === node.node_id) n.next_node_alt = node.next_node
  })
  wf.value.nodes = wf.value.nodes.filter((n) => n.node_id !== node.node_id)
  selectedId.value = null
  syncGraph()
}

async function load() {
  const [data, cat] = await Promise.all([
    call('baton.api.workflow.get_workflow', { name: route.params.workflowId }),
    call('baton.api.workflow.get_action_catalog'),
  ])
  wf.value = data
  catalog.value = cat
  syncGraph()
}

async function save() {
  if (selected.value) {
    try {
      selected.value.config = JSON.parse(configText.value || '{}')
      configError.value = ''
    } catch (e) {
      configError.value = __('Invalid JSON') + ': ' + e.message
      return
    }
  }
  saving.value = true
  try {
    wf.value = await call('baton.api.workflow.save_workflow', {
      data: JSON.stringify({ ...wf.value, name: route.params.workflowId }),
    })
    syncGraph()
    toast.success(__('Saved'))
  } finally {
    saving.value = false
  }
}

async function toggleEnabled() {
  await save()
  wf.value.enabled = await call('baton.api.workflow.set_enabled', {
    name: route.params.workflowId,
    enabled: wf.value.enabled ? 0 : 1,
  })
}

async function runTest() {
  await save()
  testing.value = true
  try {
    const res = await call('baton.api.workflow.test_run', { name: route.params.workflowId })
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
  runs.value = await call('baton.api.workflow.get_runs', { workflow: route.params.workflowId })
}

watch(showRuns, (v) => v && loadRuns())
onMounted(load)
</script>
