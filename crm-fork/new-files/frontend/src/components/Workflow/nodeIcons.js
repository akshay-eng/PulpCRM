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
import LucidePhone from '~icons/lucide/phone'
import LucideBookOpen from '~icons/lucide/book-open'
import LucideSearch from '~icons/lucide/search'
import LucideCheckCheck from '~icons/lucide/check-check'
import LucideWrench from '~icons/lucide/wrench'

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

  // A bot's own tool calls, keyed by the tool name a step's Raw JSON names --
  // distinct from the Title Case keys above, which are workflow node types.
  send_whatsapp: LucideMessageCircle,
  send_email: LucideSend,
  wait_for_reply: LucideMessageSquareDot,
  find_free_times: LucideCalendarClock,
  book_meeting: LucideCalendarCheck,
  add_note: LucideStickyNote,
  add_comment: LucideMessageSquareText,
  create_task: LucideCheckCircle,
  complete_task: LucideCheckCheck,
  assign_to: LucideUserCheck,
  convert_lead: LucideArrowRightLeft,
  log_call: LucidePhone,
  search_knowledge: LucideBookOpen,
  search: LucideSearch,
  list_pages: LucideGlobe,
  read_page: LucideGlobe,
  call_url: LucideGlobe,

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

/** A bot's own tool calls fall back to a generic tool icon, not the
 * lightning bolt a workflow's Trigger node uses -- a plain CRM lookup is
 * not the same kind of "nothing better to show" as an unrecognised node. */
export const iconForBotTool = (t) => ICONS[t] || LucideWrench
