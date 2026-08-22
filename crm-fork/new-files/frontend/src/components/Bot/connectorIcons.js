import LucideUserPlus from '~icons/lucide/user-plus'
import LucideHandshake from '~icons/lucide/handshake'
import LucideContact from '~icons/lucide/contact'
import LucideBuilding2 from '~icons/lucide/building-2'
import LucideCheckCircle from '~icons/lucide/check-circle'
import LucideStickyNote from '~icons/lucide/sticky-note'
import LucidePhone from '~icons/lucide/phone'
import LucideMessageCircle from '~icons/lucide/message-circle'
import LucideSend from '~icons/lucide/send'
import LucideCalendarClock from '~icons/lucide/calendar-clock'
import LucideGlobe from '~icons/lucide/globe'
import LucideWebhook from '~icons/lucide/webhook'
import LucidePlug from '~icons/lucide/plug'

export const CONNECTOR_ICONS = {
  'user-plus': LucideUserPlus,
  handshake: LucideHandshake,
  contact: LucideContact,
  'building-2': LucideBuilding2,
  'check-circle': LucideCheckCircle,
  'sticky-note': LucideStickyNote,
  phone: LucidePhone,
  'message-circle': LucideMessageCircle,
  send: LucideSend,
  'calendar-clock': LucideCalendarClock,
  globe: LucideGlobe,
  webhook: LucideWebhook,
}

export const connectorIcon = (name) => CONNECTOR_ICONS[name] || LucidePlug
