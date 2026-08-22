<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[
        { label: __('AI Automation'), route: { name: 'Automation' } },
        { label: __('Workflows'), route: { name: 'Workflows' } },
      ]" />
    </template>
    <template #right-header>
      <Button variant="solid" :label="__('New workflow')" :loading="creating" @click="create">
        <template #prefix><LucidePlus class="h-4 w-4" /></template>
      </Button>
    </template>
  </LayoutHeader>

  <div class="flex-1 overflow-y-auto px-6 py-5">
    <div class="mx-auto max-w-3xl">
      <div v-if="loading" class="py-10 text-center text-p-base text-ink-gray-5">
        {{ __('Loading…') }}
      </div>

      <div
        v-else-if="!workflows.length"
        class="flex flex-col items-center gap-2 rounded-xl border border-dashed border-outline-gray-2 py-14 text-ink-gray-5"
      >
        <LucideWorkflow class="h-8 w-8" />
        <div class="text-p-lg font-medium text-ink-gray-8">{{ __('No workflows yet') }}</div>
        <div class="max-w-sm text-center text-p-base">
          {{ __('Draw the steps once and they happen the same way every time — when a lead arrives, when a deal moves, on a schedule.') }}
        </div>
        <Button class="mt-2" variant="solid" :label="__('Build one')" :loading="creating" @click="create" />
      </div>

      <div v-else class="flex flex-col gap-2">
        <div
          v-for="w in workflows"
          :key="w.name"
          class="cursor-pointer rounded-lg border border-outline-gray-2 bg-surface-white px-4 py-3 transition hover:border-outline-gray-3"
          @click="open(w)"
        >
          <div class="flex items-center gap-3">
            <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-gray-2">
              <LucideWorkflow class="h-4 w-4 text-ink-gray-7" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="truncate text-p-base font-medium text-ink-gray-8">
                {{ w.workflow_name }}
              </div>
              <div class="truncate text-p-sm text-ink-gray-5">{{ triggerSummary(w) }}</div>
            </div>

            <Badge :theme="w.enabled ? 'green' : 'gray'" variant="subtle">
              {{ w.enabled ? __('Active') : __('Off') }}
            </Badge>
            <Dropdown
              :options="[{ label: __('Delete'), icon: 'trash-2', onClick: () => remove(w) }]"
              @click.stop
            >
              <Button variant="ghost">
                <template #icon><LucideMoreHorizontal class="h-4 w-4" /></template>
              </Button>
            </Dropdown>
          </div>

          <div v-if="w.description" class="mt-1 pl-11 text-p-sm text-ink-gray-6">
            {{ w.description }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import { Breadcrumbs, Button, Badge, Dropdown, call, toast } from 'frappe-ui'
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import LucideWorkflow from '~icons/lucide/workflow'
import LucidePlus from '~icons/lucide/plus'
import LucideMoreHorizontal from '~icons/lucide/more-horizontal'

const router = useRouter()
const workflows = ref([])
const loading = ref(true)
const creating = ref(false)

function triggerSummary(w) {
  const n = w.trigger_count || 0
  if (!n) return __('Runs only when you start it')
  if (n === 1) return __('When {0}', [w.trigger_summary])
  return __('{0} triggers', [n])
}

async function load() {
  loading.value = true
  try {
    workflows.value = await call('baton.api.workflow.get_workflows')
  } finally {
    loading.value = false
  }
}

const open = (w) => router.push({ name: 'Workflow', params: { workflowId: w.name } })

async function create() {
  creating.value = true
  try {
    const wf = await call('baton.api.workflow.save_workflow', {
      data: JSON.stringify({
        workflow_name: __('Untitled workflow'),
        trigger_type: 'Manual',
        triggers: [],
        nodes: [{
          node_id: 'trigger', node_type: 'Trigger', label: __('When this happens'),
          position_x: 420, position_y: 80,
        }],
      }),
    })
    open(wf)
  } catch (e) {
    toast.error(e.messages?.[0] || e.message || __('Could not create the workflow'))
  } finally {
    creating.value = false
  }
}

async function remove(w) {
  // Deleting an automation also drops its run history, which is the record of
  // everything it ever said to a customer. Worth one click of friction.
  if (!window.confirm(__('Delete “{0}”? Its run history goes too.', [w.workflow_name]))) return
  try {
    await call('baton.api.workflow.delete_workflow', { name: w.name })
    toast.success(__('Deleted'))
    await load()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not delete'))
  }
}

onMounted(load)
</script>
