import LucideZap from '~icons/lucide/zap'
import LucideGitBranch from '~icons/lucide/git-branch'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideFilePlus from '~icons/lucide/file-plus'
import LucidePlus from '~icons/lucide/plus'
import LucideSend from '~icons/lucide/send'
import LucideGlobe from '~icons/lucide/globe'
import LucideSparkles from '~icons/lucide/sparkles'
import LucidePause from '~icons/lucide/pause'
import LucideCheckSquare from '~icons/lucide/check-square'
import LucideMessageCircle from '~icons/lucide/message-circle'
import LucideMessageSquare from '~icons/lucide/message-square'
import LucideMessageSquareText from '~icons/lucide/message-square-text'
import LucideCheckCircle from '~icons/lucide/check-circle'
import LucideMessageSquareDot from '~icons/lucide/message-square-dot'
import LucideBot from '~icons/lucide/bot'
import LucideCalendarClock from '~icons/lucide/calendar-clock'
import LucideCalendarCheck from '~icons/lucide/calendar-check'
import LucideFlag from '~icons/lucide/flag'
import LucideUserCheck from '~icons/lucide/user-check'
import LucideStickyNote from '~icons/lucide/sticky-note'
import LucideArrowRightLeft from '~icons/lucide/arrow-right-left'

/** Keyed by both node type and by the catalog's `icon` name. */
export const ICONS = {
  Trigger: LucideZap,
  Condition: LucideGitBranch,
  'Update Field': LucideRefreshCw,
  'Create Document': LucideFilePlus,
  'Send Email': LucideSend,
  Webhook: LucideGlobe,
  'AI Agent': LucideSparkles,
  'AI Conversation': LucideBot,
  'Offer Slots': LucideCalendarClock,
  'Book Appointment': LucideCalendarCheck,
  Wait: LucidePause,
  'Request Approval': LucideCheckSquare,
  'Send WhatsApp': LucideMessageCircle,
  'Check Reply': LucideMessageSquare,
  'Await Reply': LucideMessageSquareDot,
  'Create Task': LucideCheckCircle,
  'Assign To': LucideUserCheck,
  'Add Comment': LucideMessageSquareText,
  'Create Note': LucideStickyNote,
  'Convert Lead': LucideArrowRightLeft,

  'git-branch': LucideGitBranch,
  'refresh-cw': LucideRefreshCw,
  'file-plus': LucideFilePlus,
  plus: LucidePlus,
  send: LucideSend,
  globe: LucideGlobe,
  sparkles: LucideSparkles,
  pause: LucidePause,
  'check-square': LucideCheckSquare,
  'message-circle': LucideMessageCircle,
  'message-square': LucideMessageSquare,
  'message-square-text': LucideMessageSquareText,
  'message-square-dot': LucideMessageSquareDot,
  'check-circle': LucideCheckCircle,
  bot: LucideBot,
  'calendar-clock': LucideCalendarClock,
  'calendar-check': LucideCalendarCheck,
  flag: LucideFlag,
  'user-check': LucideUserCheck,
  'sticky-note': LucideStickyNote,
  'arrow-right-left': LucideArrowRightLeft,
}

export const iconFor = (t) => ICONS[t] || LucideZap
