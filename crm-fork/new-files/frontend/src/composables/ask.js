import { ref } from 'vue'

// Shared open/closed state for the Ask panel. A ref rather than a store: the
// only state is a boolean, and two components need to agree on it.
export const askPanelOpen = ref(false)

export function toggleAskPanel() {
  askPanelOpen.value = !askPanelOpen.value
}

export function openAskPanel() {
  askPanelOpen.value = true
}
