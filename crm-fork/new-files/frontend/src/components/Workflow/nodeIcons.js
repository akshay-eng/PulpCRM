import LucideZap from '~icons/lucide/zap'
import LucideGitBranch from '~icons/lucide/git-branch'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideFilePlus from '~icons/lucide/file-plus'
import LucideSend from '~icons/lucide/send'
import LucideGlobe from '~icons/lucide/globe'
import LucideSparkles from '~icons/lucide/sparkles'
import LucidePause from '~icons/lucide/pause'
import LucideCheckSquare from '~icons/lucide/check-square'
import LucideMessageCircle from '~icons/lucide/message-circle'
import LucideMessageSquare from '~icons/lucide/message-square'
import LucideCheckCircle from '~icons/lucide/check-circle'

export const ICONS = {
  Trigger: LucideZap,
  Condition: LucideGitBranch,
  'Update Field': LucideRefreshCw,
  'Create Document': LucideFilePlus,
  'Send Email': LucideSend,
  Webhook: LucideGlobe,
  'AI Agent': LucideSparkles,
  Wait: LucidePause,
  'Request Approval': LucideCheckSquare,
  'Send WhatsApp': LucideMessageCircle,
  'Check Reply': LucideMessageSquare,
  'Create Task': LucideCheckCircle,
}

export const iconFor = (t) => ICONS[t] || LucideZap
