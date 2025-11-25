// Shared action metadata for Node alt UI.
// If a rich UI config becomes importable, we can swap this module to proxy it.

import path from 'path';

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

export function filteredActions(isSidechain = false) {
  if (isSidechain) {
    return ACTIONS.filter((a) => a.group === ACTION_GROUPS.nonlaunch);
  }
  return ACTIONS;
}

export function defaultExportPath(session) {
  const base = path.join(process.cwd(), 'exported-sessions');
  const agentDir = session?.agent === 'codex' ? 'codex' : 'claude';

  // Get original filename from file_path or reconstruct from session_id
  let filename;
  if (session?.file_path) {
    // Session with file_path: extract basename, change extension to .txt
    filename = path.basename(session.file_path, '.jsonl') + '.txt';
  } else {
    // Fallback: use session_id
    const id = (session?.session_id || 'session').replace(/[^a-zA-Z0-9_-]/g, '');
    filename = `${id}.txt`;
  }

  return path.join(base, agentDir, filename);
}
