<template>
  <!-- The notifications panel is absolutely positioned at `left: 100%`, so it
       needs a positioning context that is not the Sidebar itself (Sidebar sets
       overflow-x-hidden, which would clip the panel away).

       It also paints the sidebar surface: Sidebar's own `bg-surface-sidebar` is
       transparent in dark mode, and nothing behind it sets a background, so the
       column falls through to the white page canvas. The token cannot be
       overridden on the Sidebar element itself — `bg-surface-sidebar` is emitted
       after `bg-surface-gray-1` in the utilities layer and would win. -->
  <div class="relative flex h-full bg-surface-gray-1">
    <Sidebar
      v-model:collapsed="isSidebarCollapsed"
      :disable-collapse="mobile"
      :width="mobile ? '260px' : undefined"
      class="border-r border-outline-gray-1"
    >
      <div class="flex h-full flex-col px-2.5 py-3">
        <div
          class="rounded-xl border border-outline-gray-1 bg-surface-white p-1 shadow-sm"
        >
          <div
            class="flex h-12 items-center rounded-lg"
            :class="isCollapsed ? 'justify-center px-1' : 'px-2'"
            :title="isCollapsed ? __(brand.name || 'Pulp') : undefined"
          >
            <BrandLogo v-model="brand" class="size-8 shrink-0" />
            <div v-if="!isCollapsed" class="ml-2 min-w-0 flex-1 text-left">
              <div
                class="truncate text-base-medium leading-none text-ink-gray-9"
              >
                {{ __(brand.name || 'Pulp') }}
              </div>
              <div class="mt-1 truncate text-sm leading-none text-ink-gray-6">
                {{ currentUser.full_name || user }}
              </div>
            </div>
          </div>
        </div>

        <!-- Ask is intentionally treated as the primary action instead of
             another navigation row. -->
        <button
          class="pulp-ask-button mt-3"
          :class="{ 'pulp-ask-button--collapsed': isCollapsed }"
          :title="__('Ask Pulp')"
          @click="toggleAskPanel"
        >
          <TablerSparkles class="size-4 shrink-0" />
          <span v-if="!isCollapsed" class="truncate">{{ __('Ask Pulp') }}</span>
          <span
            v-if="!isCollapsed && askPanelOpen"
            class="ml-auto size-1.5 rounded-full bg-white"
          />
        </button>

        <div
          class="-mx-2.5 mt-3 flex flex-1 flex-col overflow-y-auto px-2.5 pb-3"
        >
          <nav
            class="flex flex-col gap-1"
            :aria-label="__('Primary navigation')"
          >
            <PulpNavItem
              v-for="link in primaryLinks"
              :key="link.key"
              :label="__(link.label)"
              :to="link.to"
              :active="activeItem === link.key"
              :collapsed="isCollapsed"
              @click="selectItem($event, link.key)"
            >
              <template #prefix>
                <Icon :icon="link.icon" class="size-4" />
              </template>
            </PulpNavItem>

            <PulpNavItem
              id="notifications-btn"
              :label="__('Notifications')"
              :to="mobile ? { name: 'Notifications' } : undefined"
              :active="
                mobile ? activeItem === 'Notifications' : notificationsVisible
              "
              :collapsed="isCollapsed"
              @click="onNotificationsClick"
            >
              <template #prefix>
                <span class="relative grid size-4 place-items-center">
                  <TablerBell class="size-4" />
                  <span
                    v-if="isCollapsed && unreadNotificationsCount"
                    class="absolute -right-1 -top-1 size-1.5 rounded-full bg-orange-500 ring-2 ring-[var(--surface-gray-1)]"
                  />
                </span>
              </template>
              <template #suffix>
                <Badge
                  v-if="unreadNotificationsCount"
                  :label="unreadNotificationsCount"
                  variant="subtle"
                />
              </template>
            </PulpNavItem>
          </nav>

          <nav
            v-for="section in navigationSections"
            :key="section.name"
            class="mt-4 flex flex-col gap-1"
            :aria-label="__(section.name)"
          >
            <p v-if="!isCollapsed" class="pulp-section-label">
              {{ __(section.name) }}
            </p>
            <PulpNavItem
              v-for="link in section.links"
              :key="link.key"
              :label="__(link.label)"
              :to="link.to"
              :active="activeItem === link.key"
              :collapsed="isCollapsed"
              @click="selectItem($event, link.key)"
            >
              <template #prefix>
                <Icon :icon="link.icon" class="size-4" />
              </template>
            </PulpNavItem>
          </nav>

          <details
            v-for="section in savedViewSections"
            :key="section.name"
            class="group mt-4"
            open
          >
            <summary
              v-if="!isCollapsed"
              class="pulp-section-label cursor-pointer"
            >
              <span>{{ __(section.name) }}</span>
              <TablerChevronDown
                class="size-3.5 transition-transform group-open:rotate-180"
                aria-hidden="true"
              />
            </summary>
            <nav
              class="mt-1 flex flex-col gap-1"
              :aria-label="__(section.name)"
            >
              <PulpNavItem
                v-for="link in section.links"
                :key="link.key"
                :label="__(link.label)"
                :to="link.to"
                :active="activeItem === link.key"
                :collapsed="isCollapsed"
                @click="selectItem($event, link.key)"
              >
                <template #prefix>
                  <Icon :icon="link.icon" class="size-4" />
                </template>
              </PulpNavItem>
            </nav>
          </details>
        </div>

        <div
          class="mt-auto flex flex-col gap-1 border-t border-outline-gray-1 pt-2"
        >
          <div v-if="!mobile" class="mb-1 flex flex-col gap-2">
            <SignupBanner
              v-if="isDemoSite"
              :isSidebarCollapsed="isCollapsed"
              :afterSignup="() => capture('signup_from_demo_site')"
            />
            <TrialBanner
              v-if="isFCSite"
              :isSidebarCollapsed="isCollapsed"
              :afterUpgrade="() => capture('upgrade_plan_from_trial_banner')"
            />
            <GettingStartedBanner
              v-if="!isOnboardingStepsCompleted"
              :isSidebarCollapsed="isCollapsed"
            />
          </div>
          <PulpNavItem
            v-if="!mobile && isManager() && isDemoDataCreated"
            :label="__('Clear Demo Data')"
            :collapsed="isCollapsed"
            danger
            @click="() => clearDemoData()"
          >
            <template #prefix>
              <TablerBrush class="size-4" />
            </template>
          </PulpNavItem>
          <PulpNavItem
            v-if="!mobile"
            :label="__('Settings')"
            :active="showSettings"
            :collapsed="isCollapsed"
            @click="openSettings"
          >
            <template #prefix>
              <TablerSettings class="size-4" />
            </template>
          </PulpNavItem>
          <PulpNavItem
            v-if="!mobile && isOnboardingStepsCompleted"
            :label="__('Help')"
            :active="showHelpModal"
            :collapsed="isCollapsed"
            @click="toggleHelpModal"
          >
            <template #prefix>
              <TablerHelpCircle class="size-4" />
            </template>
          </PulpNavItem>
          <PulpNavItem
            v-if="!mobile"
            :label="isCollapsed ? __('Expand') : __('Collapse')"
            :collapsed="isCollapsed"
            @click="isSidebarCollapsed = !isSidebarCollapsed"
          >
            <template #prefix>
              <TablerSidebarExpand v-if="isCollapsed" class="size-4" />
              <TablerSidebarCollapse v-else class="size-4" />
            </template>
          </PulpNavItem>
          <PulpNavItem
            :label="__('Log out')"
            :collapsed="isCollapsed"
            @click="logout.submit()"
          >
            <template #prefix>
              <TablerLogout class="size-4" />
            </template>
          </PulpNavItem>
        </div>
      </div>
    </Sidebar>
    <Notifications v-if="!mobile" />
  </div>

  <template v-if="!mobile">
    <Settings />
    <HelpModal
      v-if="showHelpModal"
      v-model="showHelpModal"
      v-model:articles="articles"
      :logo="CRMLogo"
      :afterSkip="(step) => capture('onboarding_step_skipped_' + step)"
      :afterSkipAll="() => capture('onboarding_steps_skipped')"
      :afterReset="(step) => capture('onboarding_step_reset_' + step)"
      :afterResetAll="() => capture('onboarding_steps_reset')"
      docsLink="https://pulplabs.ai"
    />
    <IntermediateStepModal
      v-model="showIntermediateModal"
      :currentStep="currentStep"
    />
  </template>
</template>

<script setup>
import {
  IconBrush as TablerBrush,
  IconLayoutDashboard as TablerLayoutDashboard,
  IconAutomation as TablerAutomation,
  IconSparkles as TablerSparkles,
  IconSettings as TablerSettings,
  IconBell as TablerBell,
  IconHelpCircle as TablerHelpCircle,
  IconLayoutSidebarLeftCollapse as TablerSidebarCollapse,
  IconLayoutSidebarLeftExpand as TablerSidebarExpand,
  IconUserSearch as TablerUserSearch,
  IconBriefcase2 as TablerBriefcase,
  IconAddressBook as TablerAddressBook,
  IconBuilding as TablerBuilding,
  IconCircleCheck as TablerCircleCheck,
  IconNote as TablerNote,
  IconPhoneCall as TablerPhoneCall,
  IconLogout as TablerLogout,
  IconPin as TablerPin,
  IconChevronDown as TablerChevronDown,
} from '@tabler/icons-vue'
import { askPanelOpen, toggleAskPanel } from '@/composables/ask'
import CRMLogo from '@/components/Icons/CRMLogo.vue'
import InviteIcon from '@/components/Icons/InviteIcon.vue'
import ConvertIcon from '@/components/Icons/ConvertIcon.vue'
import CommentIcon from '@/components/Icons/CommentIcon.vue'
import EmailIcon from '@/components/Icons/EmailIcon.vue'
import StepsIcon from '@/components/Icons/StepsIcon.vue'
import Icon from '@/components/Icon.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import PulpNavItem from '@/components/Layouts/PulpNavItem.vue'
import SquareAsterisk from '@/components/Icons/SquareAsterisk.vue'
import LeadsIcon from '@/components/Icons/LeadsIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import Notifications from '@/components/Notifications.vue'
import Settings from '@/components/Settings/Settings.vue'
import { viewsStore } from '@/stores/views'
import {
  unreadNotificationsCount,
  notificationsStore,
  visible as notificationsVisible,
} from '@/stores/notifications'
import { usersStore } from '@/stores/users'
import { sessionStore } from '@/stores/session'
import { getSettings } from '@/stores/settings'
import {
  showSettings,
  activeSettingsPage,
  mobileSidebarOpened,
} from '@/composables/settings'
import { showChangePasswordModal } from '@/composables/modals'
import { useBroadcast } from '@/composables/useBroadcast.js'
import { call, Sidebar } from 'frappe-ui'
import {
  SignupBanner,
  TrialBanner,
  HelpModal,
  GettingStartedBanner,
  useOnboarding,
  showHelpModal,
  minimize,
  IntermediateStepModal,
  useTelemetry,
} from 'frappe-ui/frappe'
import router from '@/router'
import { useStorage } from '@vueuse/core'
import { useDemoData } from '@/composables/demoData'
import { ref, reactive, computed, markRaw, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps({
  mobile: { type: Boolean, default: false },
})

const route = useRoute()

const { brand } = getSettings()
const { user, logout } = sessionStore()
const { users, isManager, getUser } = usersStore()
const currentUser = computed(() => getUser() || {})

const { getPinnedViews, getPublicViews } = viewsStore()
const { toggle: toggleNotificationPanel } = notificationsStore()
const { capture } = useTelemetry()
const { clearDemoData, isDemoDataCreated } = useDemoData()
const { send } = useBroadcast()

const isSidebarCollapsed = useStorage('isSidebarCollapsed', false)

// The mobile drawer pins the sidebar open, so it is never visually collapsed
// even when the stored rail state says otherwise.
const isCollapsed = computed(() => isSidebarCollapsed.value && !props.mobile)

const isFCSite = ref(window.is_fc_site)
const isDemoSite = ref(window.is_demo_site)

function navLink(label, icon, routeName) {
  return {
    label,
    icon,
    key: routeName,
    to: { name: routeName },
  }
}

const primaryLinks = computed(() =>
  props.mobile ? [] : [navLink('Overview', TablerLayoutDashboard, 'Dashboard')],
)

// Group by user intent, rather than exposing every data type as a peer. This
// keeps frequently paired destinations visually close without hiding routes in
// another interaction layer.
const navigationSections = computed(() => [
  {
    name: 'Pipeline',
    links: [
      navLink('Leads', TablerUserSearch, 'Leads'),
      navLink('Deals', TablerBriefcase, 'Deals'),
    ],
  },
  {
    name: 'Relationships',
    links: [
      navLink('Contacts', TablerAddressBook, 'Contacts'),
      navLink('Companies', TablerBuilding, 'Organizations'),
    ],
  },
  {
    name: 'Productivity',
    links: [
      navLink('Tasks', TablerCircleCheck, 'Tasks'),
      navLink('Notes', TablerNote, 'Notes'),
      navLink('Calls', TablerPhoneCall, 'Call Logs'),
    ],
  },
  {
    name: 'Automation',
    links: [navLink('AI Automations', TablerAutomation, 'Automation')],
  },
])

const savedViewSections = computed(() => {
  const sections = []
  if (getPublicViews().length) {
    sections.push({
      name: 'Public Views',
      links: parseView(getPublicViews()),
    })
  }

  if (getPinnedViews().length) {
    sections.push({
      name: 'Pinned Views',
      links: parseView(getPinnedViews()),
    })
  }
  return sections
})

function parseView(views) {
  return views.map((view) => {
    return {
      label: view.label,
      icon: getIcon(view.route_name, view.icon),
      key: view.name,
      to: {
        name: view.route_name,
        params: { viewType: view.type || 'list' },
        query: { view: view.name },
      },
    }
  })
}

function getIcon(routeName, icon) {
  if (icon) return icon

  switch (routeName) {
    case 'Leads':
      return TablerUserSearch
    case 'Deals':
      return TablerBriefcase
    case 'Contacts':
      return TablerAddressBook
    case 'Organizations':
      return TablerBuilding
    case 'Notes':
      return TablerNote
    case 'Tasks':
      return TablerCircleCheck
    case 'Call Logs':
      return TablerPhoneCall
    case 'Automation':
      return TablerAutomation
    default:
      return TablerPin
  }
}

// A saved view's key is its name; a plain nav item's key is its route name.
function currentRouteKey() {
  if (route.query.view) return route.query.view

  const parentRoutes = {
    Lead: 'Leads',
    Deal: 'Deals',
    Contact: 'Contacts',
    Organization: 'Organizations',
    Workflows: 'Automation',
    Workflow: 'Automation',
    Bots: 'Automation',
    Bot: 'Automation',
  }
  return parentRoutes[route.name] || route.name
}

// Set the highlight on click rather than waiting for the route, since route
// components are lazily imported and the first visit waits on a chunk fetch.
// Modified clicks open a new tab without navigating this one, so they must not
// move the highlight here.
const activeItem = ref(currentRouteKey())

function selectItem(event, key) {
  if (
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    event.button === 1
  ) {
    return
  }
  activeItem.value = key
  // Selecting the row for the route already open leaves the URL unchanged, so
  // the drawer's navigation watcher never fires. Close it here too.
  if (props.mobile) {
    mobileSidebarOpened.value = false
  }
}

watch(
  () => [route.name, route.query.view],
  () => (activeItem.value = currentRouteKey()),
)

function onNotificationsClick(event) {
  if (props.mobile) {
    selectItem(event, 'Notifications')
  } else {
    toggleNotificationPanel()
  }
}

function openSettings() {
  if (!activeSettingsPage.value) activeSettingsPage.value = 'Profile'
  showSettings.value = true
}

function toggleHelpModal() {
  showHelpModal.value = minimize.value ? true : !showHelpModal.value
  minimize.value = !showHelpModal.value
}

// onboarding
const { isOnboardingStepsCompleted, setUp } = useOnboarding('frappecrm')

async function getFirstLead() {
  let firstLead = localStorage.getItem('firstLead' + user)
  if (firstLead) return firstLead
  return await call('crm.api.onboarding.get_first_lead')
}

async function getFirstDeal() {
  let firstDeal = localStorage.getItem('firstDeal' + user)
  if (firstDeal) return firstDeal
  return await call('crm.api.onboarding.get_first_deal')
}

const showIntermediateModal = ref(false)
const currentStep = ref({})

const steps = reactive([
  {
    name: 'setup_your_password',
    title: __('Setup your password'),
    icon: markRaw(SquareAsterisk),
    completed: false,
    onClick: () => {
      minimize.value = true
      showChangePasswordModal.value = true
      capture('onboarding_step_clicked_setup_password')
    },
  },
  {
    name: 'create_first_lead',
    title: __('Create your first lead'),
    icon: markRaw(LeadsIcon),
    completed: false,
    onClick: () => {
      minimize.value = true
      router.push({ name: 'Leads' })
      send('trigger_lead_create', true)
      capture('onboarding_step_clicked_create_first_lead')
    },
  },
  {
    name: 'invite_your_team',
    title: __('Invite your team'),
    icon: markRaw(InviteIcon),
    completed: false,
    onClick: () => {
      minimize.value = true
      showSettings.value = true
      activeSettingsPage.value = 'Invite User'
      capture('onboarding_step_clicked_invite_your_team')
    },
    condition: () => isManager(),
  },
  {
    name: 'convert_lead_to_deal',
    title: __('Convert lead to deal'),
    icon: markRaw(ConvertIcon),
    completed: false,
    dependsOn: 'create_first_lead',
    onClick: async () => {
      minimize.value = true
      capture('onboarding_step_clicked_convert_lead_to_deal')
      currentStep.value = {
        title: __('Convert lead to deal'),
        buttonLabel: __('Convert'),
        videoURL: '/assets/crm/videos/convertToDeal.mov',
        onClick: async () => {
          showIntermediateModal.value = false
          currentStep.value = {}

          let lead = await getFirstLead()
          if (lead) {
            router.push({ name: 'Lead', params: { leadId: lead } })
          } else {
            router.push({ name: 'Leads' })
          }
        },
      }
      showIntermediateModal.value = true
    },
  },
  {
    name: 'create_first_task',
    title: __('Create your first task'),
    icon: markRaw(TaskIcon),
    completed: false,
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_create_first_task')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#tasks',
        })
      } else {
        router.push({ name: 'Tasks' })
      }
    },
  },
  {
    name: 'create_first_note',
    title: __('Create your first note'),
    icon: markRaw(NoteIcon),
    completed: false,
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_create_first_note')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#notes',
        })
      } else {
        router.push({ name: 'Notes' })
      }
    },
  },
  {
    name: 'add_first_comment',
    title: __('Add your first comment'),
    icon: markRaw(CommentIcon),
    completed: false,
    dependsOn: 'create_first_lead',
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_add_first_comment')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#comments',
        })
      } else {
        router.push({ name: 'Leads' })
      }
    },
  },
  {
    name: 'send_first_email',
    title: __('Send email'),
    icon: markRaw(EmailIcon),
    completed: false,
    dependsOn: 'create_first_lead',
    onClick: async () => {
      minimize.value = true
      let deal = await getFirstDeal()
      capture('onboarding_step_clicked_send_first_email')

      if (deal) {
        router.push({
          name: 'Deal',
          params: { dealId: deal },
          hash: '#emails',
        })
      } else {
        router.push({ name: 'Leads' })
      }
    },
  },
  {
    name: 'change_deal_status',
    title: __('Change deal status'),
    icon: markRaw(StepsIcon),
    completed: false,
    dependsOn: 'convert_lead_to_deal',
    onClick: async () => {
      minimize.value = true
      capture('onboarding_step_clicked_change_deal_status')

      currentStep.value = {
        title: __('Change deal status'),
        buttonLabel: __('Change'),
        videoURL: '/assets/crm/videos/changeDealStatus.mov',
        onClick: async () => {
          showIntermediateModal.value = false
          currentStep.value = {}

          let deal = await getFirstDeal()
          if (deal) {
            router.push({
              name: 'Deal',
              params: { dealId: deal },
              hash: '#activity',
            })
          } else {
            router.push({ name: 'Leads' })
          }
        },
      }
      showIntermediateModal.value = true
    },
  },
])

onMounted(async () => {
  if (props.mobile) return

  await users.promise

  const filteredSteps = steps.filter((step) => {
    if (step.condition) {
      return step.condition()
    }
    return true
  })

  setUp(filteredSteps)
})

// help center
const articles = ref([
  {
    title: __('Introduction'),
    opened: false,
    subArticles: [
      { name: 'introduction', title: __('Introduction') },
      { name: 'setting-up', title: __('Setting Up') },
    ],
  },
  {
    title: __('Settings'),
    opened: false,
    subArticles: [
      { name: 'profile', title: __('Profile') },
      { name: 'custom-branding', title: __('Custom Branding') },
      { name: 'home-actions', title: __('Home Actions') },
      { name: 'invite-users', title: __('Invite Users') },
    ],
  },
  {
    title: __('Masters'),
    opened: false,
    subArticles: [
      { name: 'lead', title: __('Lead') },
      { name: 'deal', title: __('Deal') },
      { name: 'contact', title: __('Contact') },
      { name: 'organization', title: __('Organization') },
      { name: 'note', title: __('Note') },
      { name: 'task', title: __('Task') },
      { name: 'call-log', title: __('Call Log') },
      { name: 'email-template', title: __('Email Template') },
    ],
  },
  {
    title: __('Capturing Leads'),
    opened: false,
    subArticles: [{ name: 'web-form', title: __('Web Form') }],
  },
  {
    title: __('Views'),
    opened: false,
    subArticles: [
      { name: 'view', title: __('Saved View') },
      { name: 'public-view', title: __('Public View') },
      { name: 'pinned-view', title: __('Pinned View') },
    ],
  },
  {
    title: __('Other Features'),
    opened: false,
    subArticles: [
      { name: 'email-communication', title: __('Email Communication') },
      { name: 'comment', title: __('Comment') },
      { name: 'data', title: __('Data') },
      { name: 'service-level-agreement', title: __('Service Level Agreement') },
      { name: 'assignment-rule', title: __('Assignment Rule') },
      { name: 'notification', title: __('Notification') },
    ],
  },
  {
    title: __('Customization'),
    opened: false,
    subArticles: [
      { name: 'custom-fields', title: __('Custom Fields') },
      { name: 'custom-actions', title: __('Custom Actions') },
      { name: 'custom-statuses', title: __('Custom Statuses') },
      { name: 'custom-list-actions', title: __('Custom List Actions') },
      { name: 'quick-entry-layout', title: __('Quick Entry Layout') },
    ],
  },
  {
    title: __('Integration'),
    opened: false,
    subArticles: [
      { name: 'twilio', title: __('Twilio') },
      { name: 'exotel', title: __('Exotel') },
      { name: 'whatsapp', title: __('WhatsApp') },
      { name: 'erpnext', title: __('ERPNext') },
    ],
  },
  {
    title: __('Pulp mobile'),
    opened: false,
    subArticles: [
      { name: 'mobile-app-installation', title: __('Mobile App Installation') },
    ],
  },
])
</script>

<style scoped>
.pulp-ask-button {
  display: flex;
  min-height: 2.5rem;
  width: 100%;
  align-items: center;
  gap: 0.625rem;
  border-radius: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: linear-gradient(135deg, #f97316, #ea580c);
  color: white;
  font-size: 0.875rem;
  font-weight: 600;
  box-shadow: 0 6px 18px rgb(234 88 12 / 0.18);
  transition:
    transform 150ms ease,
    box-shadow 150ms ease,
    filter 150ms ease;
}

.pulp-ask-button:hover {
  filter: saturate(1.08) brightness(1.03);
  box-shadow: 0 8px 22px rgb(234 88 12 / 0.24);
  transform: translateY(-1px);
}

.pulp-ask-button:active {
  transform: translateY(0);
}

.pulp-ask-button--collapsed {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.pulp-section-label {
  display: flex;
  min-height: 1.5rem;
  align-items: center;
  justify-content: space-between;
  padding: 0 0.625rem;
  color: var(--ink-gray-5);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  line-height: 1rem;
  text-transform: uppercase;
}

summary.pulp-section-label {
  list-style: none;
}

summary.pulp-section-label::-webkit-details-marker {
  display: none;
}
</style>
