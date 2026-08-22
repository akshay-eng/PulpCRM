<template>
  <BaseEdge :id="id" :path="path[0]" :marker-end="markerEnd" :style="style" />
  <EdgeLabelRenderer>
    <div
      :style="{
        transform: `translate(-50%, -50%) translate(${path[1]}px, ${path[2]}px)`,
      }"
      class="pointer-events-auto absolute"
      @mouseenter="hover = true"
      @mouseleave="hover = false"
    >
      <button
        v-show="hover || selected"
        class="flex h-5 w-5 items-center justify-center rounded-full border border-outline-gray-3 bg-surface-white text-ink-gray-6 shadow-sm hover:border-red-400 hover:text-red-600"
        :title="__('Remove this connection')"
        @click.stop="$emit('remove', { source, sourceHandle })"
      >
        <LucideX class="h-3 w-3" />
      </button>
    </div>
  </EdgeLabelRenderer>
</template>

<script setup>
/**
 * A connection you can actually delete.
 *
 * The stock edge has no affordance for removal, so a mis-drawn link could only
 * be undone by deleting one of the nodes it joined. Removing an edge here means
 * clearing next_node / next_node_alt on the source, which is the only place
 * that link is stored -- edges are derived from those fields, not held
 * separately.
 */
import { computed, ref } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from '@vue-flow/core'
import LucideX from '~icons/lucide/x'

const props = defineProps({
  id: String,
  source: String,
  sourceHandle: String,
  sourceX: Number,
  sourceY: Number,
  targetX: Number,
  targetY: Number,
  sourcePosition: String,
  targetPosition: String,
  markerEnd: String,
  style: Object,
  selected: Boolean,
})
defineEmits(['remove'])

const hover = ref(false)

const path = computed(() =>
  getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  }),
)
</script>
