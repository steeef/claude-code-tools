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
    value: 'resume',
    label: 'Resume session',
    group: ACTION_GROUPS.launch,
    requiresPath: false,
    hint: null,
  },
  {
    value: 'clone',
    label: 'Clone session and resume clone',
    group: ACTION_GROUPS.launch,
    requiresPath: false,
    hint: null,
  },
  {
    value: 'continue',
    label: 'Continue with context in fresh session',
    group: ACTION_GROUPS.launch,
    requiresPath: false,
    hint: null,
  },
];

export function filteredActions(isSidechain = false) {
  if (isSidechain) {
    return ACTIONS.filter((a) => a.group === ACTION_GROUPS.nonlaunch);
  }
  return ACTIONS;
}

export function defaultExportPath(session) {
  const today = new Date();
  const yyyymmdd = today.toISOString().slice(0, 10).replace(/-/g, '');
  const base = path.join(process.cwd(), 'exported-sessions');
  const id = (session?.session_id || 'session').replace(/[^a-zA-Z0-9_-]/g, '');
  return path.join(base, `${yyyymmdd}-claude-session-${id}.txt`);
}
