<template>
  <SettingsLayoutBase
    :title="__('AI Agents')"
    :description="__('An agent asks the customer questions and reports back what it learned. It can only choose between options you define here.')"
  >
    <template #header-actions>
      <Button variant="solid" :label="__('New agent')" @click="create" />
    </template>

    <template #content>
      <div v-if="loading" class="py-8 text-center text-p-base text-ink-gray-5">
        {{ __('Loading…') }}
      </div>

      <div
        v-else-if="!agents.length"
        class="flex flex-col items-center gap-2 rounded-lg border border-dashed border-outline-gray-2 py-10 text-ink-gray-5"
      >
        <LucideBot class="h-7 w-7" />
        <div class="text-p-base font-medium text-ink-gray-7">{{ __('No agents yet') }}</div>
      </div>

      <div v-else class="flex gap-6">
        <div class="w-[220px] shrink-0 border-r border-outline-gray-1 pr-3">
          <button
            v-for="a in agents"
            :key="a.name"
            class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-p-sm"
            :class="a.name === selectedName ? 'bg-surface-gray-3 text-ink-gray-9' : 'text-ink-gray-7 hover:bg-surface-gray-2'"
            @click="select(a.name)"
          >
            <LucideBot class="h-4 w-4 shrink-0" />
            <span class="truncate">{{ a.name }}</span>
            <Badge v-if="!a.enabled" theme="gray" variant="subtle" class="ml-auto">
              {{ __('Off') }}
            </Badge>
          </button>
        </div>

        <div v-if="agent" class="min-w-0 flex-1">
          <div class="mb-4 flex items-center gap-3">
            <Switch v-model="agent.enabled" :label="agent.enabled ? __('Enabled') : __('Disabled')" />
            <Button class="ml-auto" :label="__('Test')" :loading="testing" @click="test" />
            <Button variant="solid" :label="__('Save')" :loading="saving" @click="save" />
          </div>

          <FormControl v-model="agent.goal" type="textarea" :label="__('Goal')" class="mb-3" />
          <FormControl v-model="agent.persona" type="textarea" :label="__('Tone')" class="mb-3" />
          <FormControl
            v-model="agent.business_context"
            type="textarea"
            :label="__('Business context')"
            class="mb-3"
          />
          <FormControl
            v-model="agent.guardrails"
            type="textarea"
            :label="__('Guardrails')"
            class="mb-4"
          />

          <div class="mb-2 text-p-sm font-medium text-ink-gray-7">
            {{ __('Options it chooses between') }}
          </div>
          <div v-for="(o, i) in agent.options" :key="i" class="mb-2 flex gap-2">
            <FormControl v-model="o.key" type="text" :placeholder="__('key')" class="w-[130px]" />
            <FormControl v-model="o.label" type="text" :placeholder="__('Label')" class="flex-1" />
            <button class="text-ink-gray-5 hover:text-red-600" @click="agent.options.splice(i, 1)">
              <LucideX class="h-4 w-4" />
            </button>
          </div>
          <Button
            :label="__('Add option')"
            class="mb-4"
            @click="agent.options.push({ key: '', label: '' })"
          />

          <div class="mb-2 text-p-sm font-medium text-ink-gray-7">
            {{ __('Facts it should find out') }}
          </div>
          <div v-for="(o, i) in agent.outcomes" :key="'o' + i" class="mb-2 flex items-center gap-2">
            <FormControl v-model="o.key" type="text" :placeholder="__('key')" class="w-[130px]" />
            <FormControl v-model="o.label" type="text" :placeholder="__('Label')" class="flex-1" />
            <Checkbox v-model="o.required" :label="__('Required')" />
            <button class="text-ink-gray-5 hover:text-red-600" @click="agent.outcomes.splice(i, 1)">
              <LucideX class="h-4 w-4" />
            </button>
          </div>
          <Button
            :label="__('Add fact')"
            @click="agent.outcomes.push({ key: '', label: '', required: 0 })"
          />

          <div v-if="result" class="mt-5 rounded-lg border border-outline-gray-2 p-3">
            <div class="mb-1 text-xs font-medium text-ink-gray-5">
              {{ __('It would') }} <span class="font-mono">{{ result.action }}</span>
            </div>
            <div v-if="result.message" class="text-p-base text-ink-gray-8">
              “{{ result.message }}”
            </div>
            <div class="mt-1 text-xs text-ink-gray-5">{{ result.reason }}</div>
            <div v-if="result.dropped?.length" class="mt-1 text-xs text-amber-600">
              {{ __('Ignored from the model: {0}', [result.dropped.join(', ')]) }}
            </div>
          </div>
        </div>
      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup>
/**
 * The Test button is a dry run: it asks the model what it would say next about
 * the most recent lead and shows the answer. It sends nothing, which is what
 * makes it safe to press while an agent is still being written.
 */
import SettingsLayoutBase from '@/components/Layouts/SettingsLayoutBase.vue'
import { Badge, Button, Checkbox, FormControl, Switch, call, toast } from 'frappe-ui'
import { ref, onMounted } from 'vue'
import LucideBot from '~icons/lucide/bot'
import LucideX from '~icons/lucide/x'

const agents = ref([])
const agent = ref(null)
const selectedName = ref(null)
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const result = ref(null)

async function load() {
  loading.value = true
  try {
    agents.value = await call('baton.api.agent.get_agents')
    if (agents.value.length) await select(agents.value[0].name)
  } finally {
    loading.value = false
  }
}

async function select(name) {
  selectedName.value = name
  result.value = null
  agent.value = await call('baton.api.agent.get_agent', { name })
}

async function create() {
  const created = await call('baton.api.agent.save_agent', {
    data: JSON.stringify({
      agent_name: __('New agent'),
      goal: __('Find out what the customer needs.'),
      options: [],
      outcomes: [],
    }),
  })
  await load()
  await select(created.agent_name)
}

async function save() {
  saving.value = true
  try {
    agent.value = await call('baton.api.agent.save_agent', {
      data: JSON.stringify(agent.value),
    })
    await load()
    toast.success(__('Saved'))
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not save'))
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  result.value = null
  try {
    result.value = await call('baton.api.agent.test_agent', { name: agent.value.agent_name })
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not run the test'))
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>
