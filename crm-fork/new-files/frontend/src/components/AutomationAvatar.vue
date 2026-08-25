<template>
  <span
    class="automation-avatar"
    :class="`automation-avatar--${size}`"
    :style="{ backgroundImage: gradient }"
    aria-hidden="true"
  >
    <TablerRobot v-if="kind === 'bot'" />
    <TablerRoute v-else />
  </span>
</template>

<script setup>
import { computed } from 'vue'
import {
  IconRobot as TablerRobot,
  IconRoute as TablerRoute,
} from '@tabler/icons-vue'
import { automationGradient } from '@/utils/automationAvatar'

const props = defineProps({
  identity: { type: String, required: true },
  kind: {
    type: String,
    default: 'workflow',
    validator: (value) => ['bot', 'workflow'].includes(value),
  },
  size: {
    type: String,
    default: 'md',
    validator: (value) => ['sm', 'md', 'lg'].includes(value),
  },
})

const gradient = computed(() =>
  automationGradient(`${props.kind}:${props.identity}`),
)
</script>

<style scoped>
.automation-avatar {
  display: inline-grid;
  flex: none;
  place-items: center;
  border: 1px solid rgb(255 255 255 / 28%);
  color: white;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 22%),
    0 1px 2px rgb(15 23 42 / 18%);
}

.automation-avatar--sm {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 0.55rem;
}

.automation-avatar--md {
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.7rem;
}

.automation-avatar--lg {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.85rem;
}

.automation-avatar :deep(svg) {
  width: 48%;
  height: 48%;
  stroke-width: 2;
  filter: drop-shadow(0 1px 1px rgb(15 23 42 / 22%));
}
</style>
