#!/usr/bin/env node
import fs from 'fs';
import meow from 'meow';
import React, {useState} from 'react';
import {render, Box, Text, useApp, useInput, useStdout} from 'ink';
import SelectInput from 'ink-select-input';
import chalk from 'chalk';
import figures from 'figures';
import {spawnSync} from 'child_process';

const h = React.createElement;

const cli = meow(
  `Usage: node menu.js --data payload.json --out result.json`,
  {
    importMeta: import.meta,
    flags: {
      data: {type: 'string', isRequired: true},
      out: {type: 'string', isRequired: true},
    },
  }
);

const payload = JSON.parse(fs.readFileSync(cli.flags.data, 'utf8'));
const sessions = payload.sessions || [];
const keywords = payload.keywords || [];
const outPath = cli.flags.out;
const focusId = payload.focus_id || null;
const startAction = payload.start_action || false;
const rpcPath = payload.rpc_path || null;
const scopeLine = payload.scope_line || '';
const tipLine = payload.tip_line || '';
const BRANCH_ICON = '';
const DATE_FMT = new Intl.DateTimeFormat('en', {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

const DATE_DAY_FMT = new Intl.DateTimeFormat('en', {
  month: 'short',
  day: 'numeric',
});

const TIME_FMT = new Intl.DateTimeFormat('en', {
  hour: '2-digit',
  minute: '2-digit',
});

const toAnno = (s) => {
  const annos = [];
  if (s.derivation_type === 'continue' || s.derivation_type === 'continuation' || s.is_continuation) annos.push('c');
  if (s.is_trimmed || s.derivation_type === 'trim') annos.push('t');
  if (s.is_sidechain) annos.push('sub');
  return annos.length ? `(${annos.join(',')})` : '';
};

const formatLines = (lines) => (Number.isFinite(lines) ? `${lines} lines` : '');
const formatDateRange = (start, end) => {
  if (Number.isFinite(start) && Number.isFinite(end)) {
    const sDay = DATE_DAY_FMT.format(new Date(start * 1000));
    const eDay = DATE_DAY_FMT.format(new Date(end * 1000));
    const eTime = TIME_FMT.format(new Date(end * 1000));
    if (sDay === eDay) return `${eDay}, ${eTime}`;
    return `${sDay} - ${eDay}, ${eTime}`;
  }
  if (Number.isFinite(end)) return DATE_FMT.format(new Date(end * 1000));
  if (Number.isFinite(start)) return DATE_FMT.format(new Date(start * 1000));
  return '';
};

const colorize = {
  agent: (txt) => chalk.magenta(txt),
  project: (txt) => chalk.green(txt),
  branch: (txt) => chalk.cyan(txt),
  lines: (txt) => chalk.yellow(txt),
  date: (txt) => chalk.blue(txt),
};

// Non-TTY fallback: pick first session and resume
if (!process.stdout.isTTY) {
  if (sessions.length) {
    fs.writeFileSync(
      outPath,
      JSON.stringify({session_id: sessions[0].session_id, action: 'resume', kwargs: {}}),
      'utf8'
    );
    process.exit(0);
  }
  process.exit(1);
}

function writeResult(sessionId, action, kwargs = {}) {
  fs.writeFileSync(outPath, JSON.stringify({session_id: sessionId, action, kwargs}), 'utf8');
}

function SessionRow({session, active, index, width, pad}) {
  const id = (session.session_id || '').slice(0, 8);
  const anno = toAnno(session);
  const lines = formatLines(session.lines);
  const date = formatDateRange(session.create_time, session.mod_time);
  const preview = session.preview || '';
  const maxPreview = Math.max(0, width - 30);
  const trimmedPreview = preview.length > maxPreview
    ? preview.slice(0, maxPreview - 1) + '…'
    : preview;

  const agentIdRaw = `[${session.agent_display}] ${id}${anno ? ' ' + anno : ''}`;
  const agentIdPart = colorize.agent(agentIdRaw.padEnd(pad.agentId));
  const projPart = colorize.project((session.project || '').padEnd(pad.project));
  const branchRaw = session.branch ? `${BRANCH_ICON} ${session.branch}` : '';
  const branchPart = colorize.branch(branchRaw.padEnd(pad.branch));
  const linesPart = colorize.lines((lines || '').padEnd(pad.lines));
  const datePart = colorize.date((date || '').padEnd(pad.date));
  const header = `${(index + 1).toString().padEnd(2)} ${agentIdPart} | ${projPart} | ${branchPart} | ${linesPart} | ${datePart}`;
  return h(
    Box,
    {flexDirection: 'column'},
    h(
      Text,
      {
        color: active ? 'white' : 'white',
        backgroundColor: active ? '#303030' : undefined,
      },
      `${active ? figures.pointer : ' '} ${header}`
    ),
    preview
      ? h(Text, {dimColor: true}, trimmedPreview)
      : h(Text, {dimColor: true}, 'No preview available')
  );
}

function ResultsView({onSelect, onQuit, clearScreen = () => {}}) {
  const initialIndex = focusId
    ? Math.max(0, sessions.findIndex((s) => s.session_id === focusId))
    : 0;
  const [index, setIndex] = useState(initialIndex);
  const [scroll, setScroll] = useState(0);
  const [numBuffer, setNumBuffer] = useState('');
  const {stdout} = useStdout();
  const width = stdout?.columns || 80;
  const height = stdout?.rows || 24;
  const headerRows = 3; // title + blank + maybe kw
  const footerRows = 2; // instruction line + spacing
  const availableRows = Math.max(1, height - headerRows - footerRows);
  const maxItems = Math.max(1, Math.floor(availableRows / 2)); // 2 lines per item

  // Ensure scroll starts at top, unless focused row is below viewport
  React.useEffect(() => {
    const top = 0;
    let nextScroll = top;
    if (initialIndex >= maxItems) {
      nextScroll = Math.max(0, initialIndex - 1);
    }
    setScroll(nextScroll);
    setNumBuffer('');
  }, [initialIndex, maxItems]);

  useInput((input, key) => {
    if (key.escape) return onQuit();
    if (key.return) {
      if (numBuffer) {
        const target = Math.min(
          Math.max(parseInt(numBuffer, 10) - 1, 0),
          sessions.length - 1,
        );
        setIndex(target);
        setScroll((prev) => {
          if (target < prev) return target;
          if (target >= prev + maxItems) return target - maxItems + 1;
          return prev;
        });
        setNumBuffer('');
        return;
      }
      clearScreen();
      return onSelect(index);
    }
    if (key.upArrow || input === 'k') {
      setIndex((i) => {
        const next = Math.max(0, i - 1);
        setScroll((prev) => (next < prev ? next : prev));
        setNumBuffer('');
        return next;
      });
    }
    if (key.downArrow || input === 'j') {
      setIndex((i) => {
        const next = Math.min(sessions.length - 1, i + 1);
        setScroll((prev) => (next >= prev + maxItems ? prev + 1 : prev));
        setNumBuffer('');
        return next;
      });
    }
    const num = Number(input);
    if (!Number.isNaN(num) && num >= 0 && num <= 9) {
      const candidate = (numBuffer + input).replace(/^0+/, '') || '0';
      setNumBuffer(candidate);
    }
  });

  const kw = keywords.join(', ');
  const kwTrim = kw.length > width - 15 ? kw.slice(0, width - 18) + '…' : kw;
  const clampedScroll = Math.max(0, Math.min(scroll, Math.max(0, sessions.length - maxItems)));
  const visible = sessions.slice(clampedScroll, clampedScroll + maxItems);

  const pad = (() => {
    const proj = Math.max(...sessions.map((s) => (s.project || '').length), 0);
    const branch = Math.max(
      ...sessions.map((s) => {
        const raw = s.branch ? `${BRANCH_ICON} ${s.branch}` : '';
        return raw.length;
      }),
      0,
    );
    const lines = Math.max(...sessions.map((s) => (formatLines(s.lines) || '').length), 0);
    const date = Math.max(
      ...sessions.map((s) => (formatDateRange(s.create_time, s.mod_time) || '').length),
      0,
    );
    const agentId = Math.max(
      ...sessions.map((s) => {
        const anno = toAnno(s);
        const id = (s.session_id || '').slice(0, 8);
        return `[${s.agent_display}] ${id}${anno ? ' ' + anno : ''}`.length;
      }),
      0,
    );
    return {project: proj, branch, lines, date, agentId};
  })();

  const annoSet = new Set();
  sessions.forEach((s) => {
    const a = toAnno(s);
    if (a.includes('t')) annoSet.add('t');
    if (a.includes('c')) annoSet.add('c');
    if (a.includes('sub')) annoSet.add('sub');
  });
  const annoLine = (() => {
    if (!annoSet.size) return null;
    const parts = [];
    if (annoSet.has('t')) parts.push('(t)=trimmed');
    if (annoSet.has('c')) parts.push('(c)=continued');
    if (annoSet.has('sub')) parts.push('(sub)=sub-agent (not resumable)');
    return parts.join(' ');
  })();

  return h(
    Box,
    {flexDirection: 'column'},
    h(
      Box,
      {marginBottom: 1},
      h(Text, null, chalk.bgMagenta.white(' Sessions '), ' ', chalk.dim(kwTrim))
    ),
    h(
      Box,
      {flexDirection: 'column', gap: 0},
      visible.map((s, i) =>
        h(SessionRow, {
          key: s.session_id,
          session: s,
          active: clampedScroll + i === index,
          index: clampedScroll + i,
          width,
          pad,
        })
      )
    ),
    h(
      Box,
      {marginTop: 1},
      h(
        Text,
        {dimColor: true},
        `Enter: select  Esc: quit  ↑/↓ or j/k: move  number+Enter: jump ${numBuffer ? '[typing ' + numBuffer + ']' : ''}`
      )
    ),
    scopeLine
      ? h(
          Box,
          {marginTop: 0},
          h(Text, {dimColor: true}, scopeLine)
        )
      : null,
    tipLine
      ? h(
          Box,
          {marginTop: 0},
          h(Text, {dimColor: true}, tipLine)
        )
      : null,
    annoLine
      ? h(
          Box,
          {marginTop: 0},
          h(Text, {dimColor: true}, annoLine)
        )
      : null
  );
}

const mainActions = [
  {label: 'Resume session', value: 'resume'},
  {label: 'Show session file path', value: 'path'},
  {label: 'Copy session file', value: 'copy'},
  {label: 'Clone session and resume clone', value: 'clone'},
  {label: 'Export to text file (.txt)', value: 'export'},
  {label: 'Continue with context in fresh session', value: 'continue'},
];

const resumeOptions = [
  {label: 'Resume as-is', value: 'resume'},
  {label: 'Trim + resume', value: 'suppress_resume'},
  {label: 'Smart trim + resume', value: 'smart_trim_resume'},
];

function ConfirmView({session, actionLabel, onConfirm, onBack}) {
  useInput((input, key) => {
    if (key.escape) return onBack();
    if (key.return) return onConfirm();
  });
  return h(
    Box,
    {flexDirection: 'column'},
    h(Text, null, chalk.bgBlue.black(' Confirm action '), ' ', actionLabel),
    h(
      Text,
      {dimColor: true},
      `${(session.session_id || '').slice(0, 8)} ${toAnno(session)} ${formatLines(session.lines)} ${session.branch || ''}`
    ),
    session.preview ? h(Text, {dimColor: true}, session.preview.slice(0, 80)) : null,
    h(Box, {marginTop: 1}, h(Text, {dimColor: true}, 'Enter: run action & exit  Esc: back'))
  );
}

function ActionView({session, onBack, onDone, clearScreen}) {
  const baseItems = session.is_sidechain
    ? mainActions.filter((a) => ['path', 'copy', 'export'].includes(a.value))
    : mainActions;

  const items = baseItems.map((item, idx) => ({
    ...item,
    label: `${idx + 1}. ${item.label}`,
    number: idx + 1,
  }));

  const handleSelect = (item) => {
    onDone(item.value);
  };

  useInput((input, key) => {
    if (key.escape) {
      clearScreen();
      onBack();
    }
    const num = Number(input);
    if (!Number.isNaN(num) && num >= 1 && num <= items.length) {
        onDone(items[num - 1].value);
    }
  });

  return h(
    Box,
    {flexDirection: 'column'},
    h(Text, null, ''),
    h(
      Box,
      {flexDirection: 'column'},
      h(Text, null, chalk.bgCyan.black(' Actions '), ' ', session.project),
      h(
        Text,
        {dimColor: true},
        `${(session.session_id || '').slice(0, 8)} ${toAnno(session)} ${formatLines(session.lines)} ${session.branch || ''}`
      ),
      session.preview ? h(Text, {dimColor: true}, session.preview.slice(0, 80)) : null
    ),
    h(SelectInput, {
      items,
      onSelect: handleSelect,
      itemComponent: ({isHighlighted, label}) =>
        h(
          Text,
          {
            color: isHighlighted ? 'black' : 'white',
            backgroundColor: isHighlighted ? 'cyan' : undefined,
          },
          `${isHighlighted ? figures.pointer : ' '} ${label}`
        ),
    }),
    h(
      Box,
      {marginTop: 1},
      h(Text, {dimColor: true}, 'Enter: select  Esc: back  number: jump')
    )
  );
}

function ResumeView({onBack, onDone, session, clearScreen}) {
  useInput((input, key) => {
    if (key.escape) {
      clearScreen();
      onBack();
    }
    const num = Number(input);
    if (!Number.isNaN(num) && num >= 1 && num <= resumeOptions.length) {
      onDone(resumeOptions[num - 1].value);
    }
  });
  return h(
    Box,
    {flexDirection: 'column'},
    h(
      Box,
      {flexDirection: 'column'},
      h(Text, null, chalk.bgGreen.black(' Resume options ')),
      h(
        Text,
        {dimColor: true},
        `${(session.session_id || '').slice(0, 8)} ${toAnno(session)} ${formatLines(session.lines)} ${session.branch || ''}`
      ),
      session.preview ? h(Text, {dimColor: true}, session.preview.slice(0, 80)) : null
    ),
    h(SelectInput, {
      items: resumeOptions,
      onSelect: (item) => onDone(item.value),
      itemComponent: ({isHighlighted, label}) =>
        h(
          Text,
          {
            color: isHighlighted ? 'black' : 'white',
            backgroundColor: isHighlighted ? 'green' : undefined,
          },
          `${isHighlighted ? figures.pointer : ' '} ${label}`
        ),
    }),
    h(
      Box,
      {marginTop: 1},
      h(Text, {dimColor: true}, 'Enter: select  Esc: back')
    )
  );
}

function TrimForm({onSubmit, onBack, clearScreen}) {
  const [field, setField] = useState('tools');
  const [tools, setTools] = useState('');
  const [threshold, setThreshold] = useState('500');
  const [assistant, setAssistant] = useState('');

  useInput((input, key) => {
    if (key.escape) {
      clearScreen();
      return onBack();
    }
    if (key.return) {
      if (field === 'tools') setField('threshold');
      else if (field === 'threshold') setField('assistant');
      else if (field === 'assistant') {
        onSubmit({
          tools: tools || null,
          threshold: Number(threshold) || 500,
          trim_assistant: assistant ? Number(assistant) : null,
        });
      }
      return;
    }
    if (key.backspace || key.delete) {
      if (field === 'tools') setTools((t) => t.slice(0, -1));
      if (field === 'threshold') setThreshold((t) => t.slice(0, -1));
      if (field === 'assistant') setAssistant((t) => t.slice(0, -1));
      return;
    }
    if (input) {
      if (field === 'tools') setTools((t) => t + input);
      if (field === 'threshold') setThreshold((t) => t + input);
      if (field === 'assistant') setAssistant((t) => t + input);
    }
  });

  return h(
    Box,
    {flexDirection: 'column'},
    h(
      Box,
      {flexDirection: 'column'},
      h(Text, null, chalk.bgYellow.black(' Trim options ')),
      h(
        Text,
        {dimColor: true},
        `${(session.session_id || '').slice(0, 8)} ${toAnno(session)} ${formatLines(session.lines)} ${session.branch || ''}`
      ),
      session.preview ? h(Text, {dimColor: true}, session.preview.slice(0, 80)) : null
    ),
    h(Text, {dimColor: true}, 'Enter moves to next; Esc goes back; blank = default'),
    h(Text, null, 'Tools: ', h(Text, {color: field === 'tools' ? 'yellow' : undefined}, tools || 'all')),
    h(Text, null, 'Threshold: ', h(Text, {color: field === 'threshold' ? 'yellow' : undefined}, threshold || '500')),
    h(
      Text,
      null,
      'Assistant msgs: ',
      h(Text, {color: field === 'assistant' ? 'yellow' : undefined}, assistant || 'skip')
    )
  );
}

function NonLaunchView({session, action, rpcPath, onBack, onExit, clearScreen}) {
  const {exit} = useApp();
  const needsDest = action === 'copy' || action === 'export';
  const [dest, setDest] = useState('');
  const [stage, setStage] = useState(needsDest ? 'prompt' : 'running');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const runRpc = (destArg) => {
    if (!rpcPath) {
      setError('RPC path missing');
      setStage('result');
      return;
    }
    const req = {
      action,
      agent: session.agent,
      session_id: session.session_id,
      file_path: session.file_path,
      cwd: session.cwd,
      claude_home: session.claude_home,
      dest: destArg,
    };
    const proc = spawnSync('python3', [rpcPath], {
      input: JSON.stringify(req),
      encoding: 'utf8',
    });
    if (proc.error) {
      setError(proc.error.message);
      setStage('result');
      return;
    }
    try {
      const out = JSON.parse(proc.stdout || '{}');
      if (out.status === 'ok') {
        setMessage(out.message || 'Done');
      } else {
        setError(out.message || 'Error');
      }
    } catch (e) {
      setError(proc.stdout || 'Bad RPC output');
    }
    setStage('result');
  };

  React.useEffect(() => {
    if (stage === 'running') {
      runRpc(dest);
    }
  }, [stage]);

  useInput((input, key) => {
    if (stage === 'prompt') {
      if (key.escape) {
        clearScreen();
        return onBack();
      }
      if (key.return) {
        setStage('running');
        return;
      }
      if (key.backspace || key.delete) {
        setDest((d) => d.slice(0, -1));
        return;
      }
      if (input) setDest((d) => d + input);
    } else if (stage === 'result') {
      if (key.escape) {
        clearScreen();
        return onBack();
      }
      if (key.return) {
        onExit();
        exit({exitCode: 0});
      }
    }
  });

  return h(
    Box,
    {flexDirection: 'column'},
    h(Text, null, chalk.bgBlue.black(` ${action.toUpperCase()} `), ' ', session.project),
    h(
      Text,
      {dimColor: true},
      `${(session.session_id || '').slice(0, 8)} ${toAnno(session)} ${formatLines(session.lines)} ${session.branch || ''}`
    ),
    session.preview ? h(Text, {dimColor: true}, session.preview.slice(0, 80)) : null,
    stage === 'prompt'
      ? h(
          Box,
          {flexDirection: 'column', marginTop: 1},
          h(Text, null, 'Destination: ', dest || chalk.dim('type path...')),
          h(Text, {dimColor: true}, 'Enter: run  Esc: back')
        )
      : h(
          Box,
          {flexDirection: 'column', marginTop: 1},
          error ? h(Text, {color: 'red'}, error) : h(Text, {color: 'green'}, message || 'Done'),
          h(Text, {dimColor: true}, 'Enter: exit  Esc: back')
        )
  );
}

function App() {
  const {exit} = useApp();
  const {stdout} = useStdout();
  const [screen, setScreen] = useState(startAction ? 'action' : 'results');
  const [current, setCurrent] = useState(
    focusId ? Math.max(0, sessions.findIndex((s) => s.session_id === focusId)) : 0
  );
  const [nonLaunch, setNonLaunch] = useState(null);

  const safeCurrent = React.useMemo(() => {
    if (!sessions.length) return 0;
    return Math.min(Math.max(current, 0), sessions.length - 1);
  }, [current]);

  const session = sessions[safeCurrent];

  const clearScreen = React.useCallback(() => {
    try {
      if (stdout?.isTTY) {
        stdout.write('\u001b[2J');
        stdout.write('\u001b[H');
      }
    } catch (e) {
      /* ignore */
    }
  }, [stdout]);

  const switchScreen = (next) => {
    clearScreen();
    setScreen(next);
  };

  const quit = () => exit({exitCode: 0});

  const finish = (action, kwargs = {}) => {
    writeResult(session.session_id, action, kwargs);
    exit({exitCode: 0});
  };

  if (!sessions.length) {
    exit({exitCode: 0});
    return null;
  }

  let view = null;

  if (screen === 'results') {
    view = h(ResultsView, {
      onSelect: (idx) => {
        setCurrent(idx);
        switchScreen('action');
      },
      onQuit: quit,
      clearScreen,
    });
  } else if (screen === 'action') {
    view = h(ActionView, {
      session,
      onBack: () => switchScreen('results'),
      onDone: (action) => {
        if (['path', 'copy', 'export'].includes(action)) {
          setNonLaunch({action});
          switchScreen('nonlaunch');
        } else if (action === 'resume') switchScreen('resume');
        else if (action === 'suppress_resume') switchScreen('trim');
        else finish(action);
      },
      clearScreen,
    });
  } else if (screen === 'resume') {
    view = h(ResumeView, {
      session,
      onBack: () => switchScreen('action'),
      onDone: (value) => {
        if (value === 'suppress_resume') switchScreen('trim');
        else finish(value);
      },
      clearScreen,
    });
  } else if (screen === 'trim') {
    view = h(TrimForm, {
      onBack: () => switchScreen('resume'),
      onSubmit: (opts) => finish('suppress_resume', opts),
      session,
      clearScreen,
    });
  } else if (screen === 'nonlaunch') {
    view = h(NonLaunchView, {
      session,
      action: nonLaunch.action,
      rpcPath,
      onBack: () => switchScreen('action'),
      onExit: quit,
      clearScreen,
    });
  }

  return view || null;
}

render(h(App));
