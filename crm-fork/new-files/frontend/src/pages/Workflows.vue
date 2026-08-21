<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="[{ label: __('Workflows'), route: { name: 'Workflows' } }]" />
    </template>
    <template #right-header>
      <Button variant="solid" :label="__('Create')" @click="createWorkflow">
        <template #prefix><LucidePlus class="h-4 w-4" /></template>
      </Button>
    </template>
  </LayoutHeader>

  <div class="flex-1 overflow-y-auto px-5 py-4">
    <div v-if="!workflows.length" class="flex h-full flex-col items-center justify-center gap-2 text-ink-gray-5">
      <LucideWorkflow class="h-8 w-8" />
      <div class="text-base font-medium text-ink-gray-7">{{ __('No workflows yet') }}</div>
      <div class="text-sm">{{ __('Automate what happens when a lead or deal changes.') }}</div>
    </div>

    <div v-else class="flex flex-col">
      <div
        v-for="w in workflows"
        :key="w.name"
        class="flex cursor-pointer items-center gap-3 border-b border-outline-gray-1 px-2 py-3 hover:bg-surface-gray-1"
        @click="$router.push({ name: 'Workflow', params: { workflowId: w.name } })"
      >
        <LucideWorkflow class="h-4 w-4 text-ink-gray-6" />
        <div class="flex-1">
          <div class="text-base font-medium text-ink-gray-8">{{ w.workflow_name }}</div>
          <div class="text-xs text-ink-gray-5">
            {{ w.trigger_type }}<span v-if="w.trigger_doctype"> · {{ w.trigger_doctype }} · {{ w.trigger_event }}</span>
          </div>
        </div>
        <Badge :theme="w.enabled ? 'green' : 'gray'" variant="subtle">
          {{ w.enabled ? __('Active') : __('Inactive') }}
        </Badge>
      </div>
    </div>
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import { Breadcrumbs, Button, Badge, call } from 'frappe-ui'
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import LucideWorkflow from '~icons/lucide/workflow'
import LucidePlus from '~icons/lucide/plus'

const router = useRouter()
const workflows = ref([])

async function load() {
  workflows.value = await call('baton.api.workflow.get_workflows')
}

async function createWorkflow() {
  const wf = await call('baton.api.workflow.save_workflow', {
    data: JSON.stringify({
      workflow_name: __('Untitled workflow'),
      trigger_type: 'Manual',
      nodes: [{ node_id: 'trigger', node_type: 'Trigger', label: __('Launch manually') }],
    }),
  })
  router.push({ name: 'Workflow', params: { workflowId: wf.name } })
}

onMounted(load)
</script>
