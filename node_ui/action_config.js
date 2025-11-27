// Shared action metadata for Node alt UI.
// If a rich UI config becomes importable, we can swap this module to proxy it.

export const ACTION_GROUPS = {
  nonlaunch: 'nonlaunch',
  launch: 'launch',
};

// Ordered actions matching rich UI intent: first non-launch, then launch.
export const ACTIONS = [
  {
    value: 'path',
    label: 'Show session file path',
    group: ACTION_GROUPS.nonlaunch,
    requiresPath: false,
    hint: null,
  },
  {
    value: 'copy',
    label: 'Copy session file',
    group: ACTION_GROUPS.nonlaunch,
    requiresPath: true,
    hint: 'Enter destination file or directory path.',
  },
  {
    value: 'export',
    label: 'Export to text file (.txt)',
    group: ACTION_GROUPS.nonlaunch,
    requiresPath: true,
    hint: 'Leave blank to use default exported-sessions/<date>-session-<id>.txt',
  },
  {
    value: 'query',
    label: 'Query this session...',
    group: ACTION_GROUPS.nonlaunch,
    requiresPath: false,
    requiresQuery: true,
    hint: 'Ask any question about this session',
    defaultQuery: 'Summarize what was accomplished in this session',
  },
  {
    value: 'resume_menu',
    label: 'Resume/trim session...',
    group: ACTION_GROUPS.launch,
    requiresPath: false,
    hint: null,
  },
];

// Resume submenu options (shown when 'resume_menu' is selected)
export const RESUME_SUBMENU = [
  {value: 'resume', label: 'Resume as-is'},
  {value: 'clone', label: 'Clone session and resume clone'},
  {value: 'suppress_resume', label: 'Trim + resume...'},
  {value: 'smart_trim_resume', label: 'Smart trim + resume'},
  {value: 'continue', label: 'Continue with context in fresh session'},
];

// Trim-only submenu (for aichat trim command)
export const TRIM_SUBMENU = [
  {value: 'suppress_resume', label: 'Trim + resume...'},
  {value: 'smart_trim_resume', label: 'Smart trim + resume'},
];

export function filteredActions(isSidechain = false) {
  if (isSidechain) {
    return ACTIONS.filter((a) => a.group === ACTION_GROUPS.nonlaunch);
  }
  return ACTIONS;
}

