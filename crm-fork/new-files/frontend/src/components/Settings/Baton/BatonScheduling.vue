<template>
  <SettingsLayoutBase
    :title="__('Scheduling')"
    :description="__('When meetings can be booked, and how long they run. Slots are only ever offered inside these hours.')"
  >
    <template #content>
      <div v-if="loading" class="py-8 text-center text-p-base text-ink-gray-5">
        {{ __('Loading…') }}
      </div>

      <template v-else>
        <div class="mb-3 flex items-center gap-3">
          <FormControl
            v-model="selectedName"
            type="select"
            :options="config.availabilities.map((a) => a.name)"
            class="w-[240px]"
          />
          <Button class="ml-auto" :label="__('Preview slots')" :loading="previewing" @click="preview" />
          <Button variant="solid" :label="__('Save')" :loading="saving" @click="save" />
        </div>

        <div v-if="availability" class="rounded-lg border border-outline-gray-2 p-4">
          <div class="mb-4 grid grid-cols-2 gap-3">
            <FormControl v-model="availability.user" type="text" :label="__('For user')"
              :placeholder="__('Blank = everyone')" />
            <FormControl v-model="availability.timezone" type="text" :label="__('Timezone')" />
            <FormControl v-model="availability.holiday_list" type="select"
              :label="__('Holiday list')" :options="['', ...config.holiday_lists]" />
            <FormControl v-model.number="availability.slot_minutes" type="number"
              :label="__('Slot every (minutes)')" />
            <FormControl v-model.number="availability.min_notice_minutes" type="number"
              :label="__('Minimum notice (minutes)')" />
            <FormControl v-model.number="availability.max_days_ahead" type="number"
              :label="__('Look ahead (days)')" />
            <FormControl v-model.number="availability.buffer_after_minutes" type="number"
              :label="__('Gap after each meeting')" />
            <FormControl v-model.number="availability.max_bookings_per_day" type="number"
              :label="__('Max per day (0 = no limit)')" />
          </div>

          <div class="mb-2 text-p-sm font-medium text-ink-gray-7">{{ __('Working hours') }}</div>
          <div
            v-for="day in config.weekdays"
            :key="day"
            class="flex items-center gap-3 border-b border-outline-gray-1 py-2 last:border-0"
          >
            <Checkbox
              :model-value="Boolean(hoursFor(day))"
              :label="day"
              class="w-[130px]"
              @update:model-value="toggleDay(day, $event)"
            />
            <template v-if="hoursFor(day)">
              <FormControl v-model="hoursFor(day).start_time" type="time" class="w-[130px]" />
              <span class="text-ink-gray-5">{{ __('to') }}</span>
              <FormControl v-model="hoursFor(day).end_time" type="time" class="w-[130px]" />
            </template>
            <span v-else class="text-p-sm text-ink-gray-5">{{ __('Not working') }}</span>
          </div>
        </div>

        <div v-if="slots.length" class="mt-4 rounded-lg border border-outline-gray-2 p-3">
          <div class="mb-1 text-xs font-medium text-ink-gray-5">
            {{ __('Next available') }}
          </div>
          <div v-for="s in slots" :key="s.start" class="text-p-base text-ink-gray-8">
            {{ s.label }}
          </div>
        </div>
        <div v-else-if="previewed" class="mt-4 text-p-sm text-amber-600">
          {{ __('Nothing free in the look-ahead window.') }}
        </div>

        <div class="mt-8">
          <div class="mb-2 text-p-sm font-medium text-ink-gray-7">{{ __('Services') }}</div>
          <div
            v-for="s in config.services"
            :key="s.name"
            class="flex items-center gap-3 border-b border-outline-gray-1 py-2 last:border-0"
          >
            <span class="flex-1 text-p-base text-ink-gray-8">{{ s.service_name }}</span>
            <span class="text-p-sm text-ink-gray-5">{{ s.duration_minutes }} {{ __('min') }}</span>
            <Badge :theme="s.enabled ? 'green' : 'gray'" variant="subtle">
              {{ s.enabled ? __('On') : __('Off') }}
            </Badge>
          </div>
        </div>
      </template>
    </template>
  </SettingsLayoutBase>
</template>

<script setup>
import SettingsLayoutBase from '@/components/Layouts/SettingsLayoutBase.vue'
import { Badge, Button, Checkbox, FormControl, call, toast } from 'frappe-ui'
import { computed, ref, onMounted } from 'vue'

const config = ref({ availabilities: [], services: [], weekdays: [], holiday_lists: [] })
const selectedName = ref(null)
const loading = ref(true)
const saving = ref(false)
const previewing = ref(false)
const previewed = ref(false)
const slots = ref([])

const availability = computed(
  () => config.value.availabilities.find((a) => a.name === selectedName.value) || null,
)

const hoursFor = (day) =>
  availability.value?.working_hours.find((h) => h.workday === day) || null

function toggleDay(day, on) {
  const hours = availability.value.working_hours
  if (on) {
    hours.push({ workday: day, start_time: '09:00:00', end_time: '17:00:00' })
  } else {
    const i = hours.findIndex((h) => h.workday === day)
    if (i > -1) hours.splice(i, 1)
  }
}

async function load() {
  loading.value = true
  try {
    config.value = await call('baton.api.scheduling.get_config')
    if (config.value.availabilities.length) {
      selectedName.value = config.value.availabilities[0].name
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await call('baton.api.scheduling.save_availability', {
      data: JSON.stringify(availability.value),
    })
    toast.success(__('Saved'))
    await load()
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not save'))
  } finally {
    saving.value = false
  }
}

async function preview() {
  previewing.value = true
  slots.value = []
  try {
    slots.value = await call('baton.api.scheduling.preview_slots', {
      availability: selectedName.value,
    })
    previewed.value = true
  } catch (e) {
    toast.error(e.messages?.[0] || __('Could not read the calendar'))
  } finally {
    previewing.value = false
  }
}

onMounted(load)
</script>
