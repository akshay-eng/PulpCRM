<template>
  <aside
      v-if="open"
      class="flex w-[400px] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-white"
    >
      <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-3">
        <div class="flex items-center gap-2">
          <LucideSparkles class="h-4 w-4 text-orange-500" />
          <span class="text-base font-medium text-ink-gray-8">{{ __('Ask') }}</span>
        </div>
        <div class="flex items-center gap-1">
          <Button variant="ghost" :label="__('New chat')" size="sm" @click="reset">
            <template #prefix><LucidePlus class="h-3.5 w-3.5" /></template>
          </Button>
          <button class="p-1 text-ink-gray-5 hover:text-ink-gray-8" @click="close">
            <LucideX class="h-4 w-4" />
          </button>
        </div>
      </div>

      <div ref="scroller" class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <!-- empty state -->
        <div v-if="!turns.length" class="pt-6">
          <div class="mb-1 text-sm font-medium text-ink-gray-7">
            {{ __('What can I help you with?') }}
          </div>
          <div class="mb-4 text-xs text-ink-gray-5">
            {{ __('Ask about your leads, deals, contacts or tasks in plain English.') }}
          </div>
          <button
            v-for="s in suggestions"
            :key="s"
            class="mb-1.5 flex w-full items-center gap-2 rounded-md border border-outline-gray-2 px-2.5 py-2 text-left text-xs text-ink-gray-7 hover:border-outline-gray-3 hover:bg-surface-gray-1"
            @click="ask(s)"
          >
            <LucideSearch class="h-3.5 w-3.5 shrink-0 text-ink-gray-5" />{{ s }}
          </button>
        </div>

        <div v-for="(t, i) in turns" :key="i">
          <!-- question -->
          <div class="mb-2 flex justify-end">
            <div class="max-w-[85%] rounded-lg bg-surface-gray-3 px-3 py-1.5 text-sm text-ink-gray-8">
              {{ t.question }}
            </div>
          </div>

          <div v-if="t.pending" class="flex items-center gap-2 text-xs text-ink-gray-5">
            <LucideLoader class="h-3.5 w-3.5 animate-spin" />{{ __('Thinking…') }}
          </div>

          <div v-else-if="t.error" class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
            {{ t.error }}
          </div>

          <template v-else>
            <div class="mb-2 text-sm text-ink-gray-8">{{ t.answer }}</div>

            <div v-if="t.rows?.length" class="overflow-hidden rounded-md border border-outline-gray-2">
              <div class="max-h-72 overflow-auto">
                <table class="w-full text-xs">
                  <thead class="sticky top-0 bg-surface-gray-2">
                    <tr>
                      <th v-for="f in t.fields" :key="f"
                          class="px-2 py-1.5 text-left font-medium text-ink-gray-6">{{ f }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, ri) in t.rows" :key="ri"
                        class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
                        @click="openRecord(t.doctype, row.name)">
                      <td v-for="f in t.fields" :key="f" class="px-2 py-1.5 text-ink-gray-7">
                        {{ format(row[f]) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="flex items-center justify-between border-t border-outline-gray-1 bg-surface-gray-1 px-2 py-1">
                <span class="text-[11px] text-ink-gray-5">
                  {{ t.doctype }} · {{ t.row_count }} {{ __('rows') }}
                </span>
                <button class="text-[11px] text-ink-gray-5 underline hover:text-ink-gray-7"
                        @click="t.showQuery = !t.showQuery">
                  {{ t.showQuery ? __('hide query') : __('show query') }}
                </button>
              </div>
              <!-- Answers must be traceable to the query that produced them. -->
              <pre v-if="t.showQuery"
                   class="max-h-40 overflow-auto border-t border-outline-gray-1 bg-surface-gray-2 px-2 py-1.5 text-[11px] text-ink-gray-6">{{ JSON.stringify(t.query, null, 1) }}</pre>
            </div>

            <div v-else class="text-xs text-ink-gray-5">{{ __('No matching records.') }}</div>
          </template>
        </div>
      </div>

      <div class="border-t border-outline-gray-2 p-3">
        <div class="flex items-end gap-2 rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5">
          <textarea
            v-model="draft"
            rows="1"
            :placeholder="__('Ask about your CRM data…')"
            class="max-h-28 flex-1 resize-none bg-transparent text-sm text-ink-gray-8 placeholder:text-ink-gray-4 focus:outline-none"
            @keydown.enter.exact.prevent="ask()"
          ></textarea>
          <button
            class="rounded-md p-1 text-ink-gray-5 disabled:opacity-40 hover:text-ink-gray-8"
            :disabled="!draft.trim() || busy"
            @click="ask()"
          >
            <LucideArrowUp class="h-4 w-4" />
          </button>
        </div>
        <div class="mt-1.5 text-[11px] text-ink-gray-5">
          {{ __('Reads only what you have permission to see.') }}
        </div>
      </div>
  </aside>
</template>

<script setup>
import { Button, call } from 'frappe-ui'
import { ref, reactive, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import LucideSparkles from '~icons/lucide/sparkles'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'
import LucideSearch from '~icons/lucide/search'
import LucideLoader from '~icons/lucide/loader'
import LucideArrowUp from '~icons/lucide/arrow-up'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close'])

const router = useRouter()
const turns = ref([])
const draft = ref('')
const busy = ref(false)
const session = ref(null)
const scroller = ref(null)

const suggestions = [
  'How many open leads do we have?',
  'Show the 5 most recently modified deals',
  'Which leads came from the website?',
  'List tasks that are overdue',
]

const ROUTES = {
  'CRM Lead': 'Lead',
  'CRM Deal': 'Deal',
  Contact: 'Contact',
  'CRM Organization': 'Organization',
}

function format(v) {
  if (v === null || v === undefined || v === '') return '—'
  const s = String(v)
  return s.length > 42 ? s.slice(0, 42) + '…' : s
}

function openRecord(doctype, name) {
  const route = ROUTES[doctype]
  if (!route || !name) return
  router.push({ name: route, params: { [`${route.toLowerCase()}Id`]: name } })
}

function reset() {
  turns.value = []
  session.value = null
  draft.value = ''
}

function close() {
  emit('close')
}

async function scrollDown() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

async function ask(text) {
  const question = (text ?? draft.value).trim()
  if (!question || busy.value) return
  draft.value = ''
  busy.value = true

  // reactive(), not a plain object: pushing a plain object into a ref array
  // means Vue proxies the *copy in the array*, while this local variable still
  // points at the raw one. Object.assign on the raw object then updates nothing
  // and the turn stays stuck on "Thinking…" even after the answer arrives.
  const turn = reactive({ question, pending: true, showQuery: false })
  turns.value.push(turn)
  await scrollDown()

  try {
    const raw = await call('baton.api.chat.ask', {
      question,
      session: session.value || undefined,
    })
    const r = raw?.message ?? raw
    session.value = r.session
    Object.assign(turn, {
      pending: false, answer: r.answer, rows: r.rows, fields: r.fields,
      doctype: r.doctype, row_count: r.row_count, query: r.query,
    })
  } catch (e) {
    Object.assign(turn, { pending: false, error: e.message || String(e) })
  } finally {
    busy.value = false
    await scrollDown()
  }
}

watch(() => props.open, (v) => v && scrollDown())
</script>
