<template>
  <Tooltip
    :text="label"
    placement="right"
    :hoverDelay="0.6"
    :disabled="!collapsed"
  >
    <component
      :is="to ? RouterLink : 'a'"
      :to="to"
      :href="to ? undefined : '#'"
      :role="to ? undefined : 'button'"
      v-bind="$attrs"
      class="pulp-nav-item"
      :class="{
        'pulp-nav-item--active': active,
        'pulp-nav-item--collapsed': collapsed,
        'pulp-nav-item--danger': danger,
      }"
      :aria-current="to && active ? 'page' : undefined"
      :aria-pressed="!to ? active : undefined"
      @click="onClick"
      @keydown.space="onSpace"
    >
      <span v-if="active" class="pulp-nav-item__marker" />
      <span class="pulp-nav-item__icon">
        <slot name="prefix" />
      </span>
      <span v-if="!collapsed" class="min-w-0 flex-1 truncate text-left">
        {{ label }}
      </span>
      <span v-if="!collapsed && $slots.suffix" class="ml-auto shrink-0">
        <slot name="suffix" />
      </span>
    </component>
  </Tooltip>
</template>

<script setup>
import { Tooltip } from 'frappe-ui'
import { RouterLink } from 'vue-router'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  label: { type: String, required: true },
  to: { type: [String, Object], default: undefined },
  active: { type: Boolean, default: false },
  collapsed: { type: Boolean, default: false },
  danger: { type: Boolean, default: false },
})

const emit = defineEmits(['click'])

function onClick(event) {
  if (!props.to) event.preventDefault()
  emit('click', event)
}

function onSpace(event) {
  if (props.to) return
  event.preventDefault()
  emit('click', event)
}
</script>

<style scoped>
.pulp-nav-item {
  position: relative;
  display: flex;
  box-sizing: border-box;
  flex-direction: row;
  flex-wrap: nowrap;
  height: 2.25rem;
  min-height: 2.25rem;
  width: 100%;
  flex-shrink: 0;
  align-items: center;
  justify-content: flex-start;
  gap: 0.625rem;
  border: 1px solid transparent;
  border-radius: 0.625rem;
  padding: 0.45rem 0.625rem;
  color: var(--ink-gray-7);
  font-size: 0.875rem;
  line-height: 1.25rem;
  text-align: left;
  text-decoration: none;
  white-space: nowrap;
  transition:
    background-color 150ms ease,
    color 150ms ease,
    box-shadow 150ms ease,
    transform 150ms ease;
}

.pulp-nav-item:hover {
  background: var(--surface-gray-2);
  color: var(--ink-gray-9);
}

.pulp-nav-item--active {
  background: var(--surface-orange-2, var(--surface-gray-2));
  color: var(--ink-gray-9);
  font-weight: 500;
  box-shadow: none;
}

.pulp-nav-item--active:hover {
  background: var(--surface-orange-2, var(--surface-gray-2));
}

.pulp-nav-item:focus {
  outline: none;
}

.pulp-nav-item:focus-visible {
  border-color: var(--outline-orange-1, var(--outline-gray-3));
  box-shadow: 0 0 0 2px var(--surface-orange-2, var(--surface-gray-2));
}

.pulp-nav-item--collapsed {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.pulp-nav-item--danger {
  color: var(--ink-red-6);
}

.pulp-nav-item--danger:hover {
  background: var(--surface-red-2);
  color: var(--ink-red-6);
}

.pulp-nav-item__marker {
  position: absolute;
  top: 50%;
  left: 0;
  height: 1.1rem;
  width: 0.175rem;
  border-radius: 0 999px 999px 0;
  background: var(--surface-orange-5, #f97316);
  transform: translateY(-50%);
}

.pulp-nav-item__icon {
  display: grid;
  height: 1.125rem;
  width: 1.125rem;
  flex-shrink: 0;
  place-items: center;
}

.pulp-nav-item--active .pulp-nav-item__icon {
  color: #ea580c;
}

.pulp-nav-item__icon :deep(svg) {
  height: 1rem;
  width: 1rem;
  stroke-width: 2;
}
</style>
