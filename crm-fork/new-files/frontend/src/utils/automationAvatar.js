// A restrained set of vivid gradients keeps automations easy to distinguish
// without storing presentation data on the server. The hash makes the choice
// stable for the same record on every browser and every visit.
const AUTOMATION_GRADIENTS = [
  'linear-gradient(135deg, #f97316, #db2777)',
  'linear-gradient(135deg, #7c3aed, #2563eb)',
  'linear-gradient(135deg, #0891b2, #0f766e)',
  'linear-gradient(135deg, #059669, #65a30d)',
  'linear-gradient(135deg, #d97706, #ea580c)',
  'linear-gradient(135deg, #4f46e5, #7c3aed)',
  'linear-gradient(135deg, #0f766e, #2563eb)',
  'linear-gradient(135deg, #be123c, #7c3aed)',
  'linear-gradient(135deg, #0284c7, #4f46e5)',
  'linear-gradient(135deg, #c2410c, #ca8a04)',
  'linear-gradient(135deg, #0d9488, #059669)',
  'linear-gradient(135deg, #9333ea, #db2777)',
]

export function automationGradient(identity = '') {
  let hash = 2166136261
  for (let index = 0; index < identity.length; index += 1) {
    hash ^= identity.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }

  return AUTOMATION_GRADIENTS[(hash >>> 0) % AUTOMATION_GRADIENTS.length]
}
