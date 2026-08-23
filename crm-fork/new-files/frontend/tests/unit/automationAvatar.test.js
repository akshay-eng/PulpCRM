import { describe, expect, it } from 'vitest'
import { automationGradient } from '../../src/utils/automationAvatar'

describe('automationGradient', () => {
  it('keeps an automation color stable', () => {
    expect(automationGradient('bot:Qualification bot')).toBe(
      automationGradient('bot:Qualification bot'),
    )
  })

  it('distributes different identities across the palette', () => {
    const gradients = new Set(
      Array.from({ length: 12 }, (_, index) =>
        automationGradient(`workflow:Follow-up ${index}`),
      ),
    )

    expect(gradients.size).toBeGreaterThan(1)
  })
})
