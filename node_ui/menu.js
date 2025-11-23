#!/usr/bin/env node
import fs from 'fs';
import meow from 'meow';
import React, {useState} from 'react';
import {render, Box, Text, useApp, useInput, useStdout} from 'ink';
import SelectInput from 'ink-select-input';
import chalk from 'chalk';
import figures from 'figures';

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

function SessionRow({session, active, index, width}) {
  const id = (session.session_id || '').slice(0, 8);
  const branch = session.branch ? chalk.cyan(` ${BRANCH_ICON} ${session.branch}`) : '';
  const anno = toAnno(session);
  const lines = formatLines(session.lines);
  const date = formatDateRange(session.create_time, session.mod_time);
  const preview = session.preview || '';
  const maxPreview = Math.max(0, width - 30);
  const trimmedPreview = preview.length > maxPreview
    ? preview.slice(0, maxPreview - 1) + '…'
    : preview;
  const parts = [
    `${index + 1}. [${session.agent_display}] ${id}${anno ? ' ' + anno : ''}`,
    session.project,
    branch,
    lines,
    date,
  ].filter(Boolean);
  const header = parts.join(' | ');
  return h(
    Box,
    {flexDirection: 'column'},
    h(
      Text,
      {
        color: active ? 'black' : 'white',
        backgroundColor: active ? 'cyan' : undefined,
      },
      `${active ? figures.pointer : ' '} ${header}`
    ),
    preview
      ? h(Text, {dimColor: true}, trimmedPreview)
      : h(Text, {dimColor: true}, 'No preview available')
  );
}

function ResultsView({onSelect, onQuit}) {
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
    )
  );
}

const mainActions = [
  {label: 'Resume', value: 'resume'},
  {label: 'Show path', value: 'path'},
  {label: 'Copy file', value: 'copy'},
  {label: 'Clone + resume', value: 'clone'},
  {label: 'Export to text', value: 'export'},
  {label: 'Continue (fresh)', value: 'continue'},
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

function ActionView({session, onBack, onDone}) {
  const items = session.is_sidechain
    ? mainActions.filter((a) => ['path', 'copy', 'export'].includes(a.value))
    : mainActions;

  const handleSelect = (item) => {
    if (item.value === 'resume') {
      onDone('resume');
    } else if (item.value === 'continue') {
      onDone('continue');
    } else if (item.value === 'suppress_resume') {
      onDone('suppress_resume');
    } else {
      onDone(item.value);
    }
  };

  useInput((input, key) => {
    if (key.escape) onBack();
  });

  return h(
    Box,
    {flexDirection: 'column'},
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
      h(Text, {dimColor: true}, 'Enter: select  Esc: back')
    )
  );
}

function ResumeView({onBack, onDone, session}) {
  useInput((input, key) => {
    if (key.escape) onBack();
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

function TrimForm({onSubmit, onBack}) {
  const [field, setField] = useState('tools');
  const [tools, setTools] = useState('');
  const [threshold, setThreshold] = useState('500');
  const [assistant, setAssistant] = useState('');

  useInput((input, key) => {
    if (key.escape) return onBack();
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

function App() {
  const {exit} = useApp();
  const [screen, setScreen] = useState(startAction ? 'action' : 'results');
  const [current, setCurrent] = useState(
    focusId ? Math.max(0, sessions.findIndex((s) => s.session_id === focusId)) : 0
  );
  const session = sessions[current];

  const quit = () => exit({exitCode: 0});

  const finish = (action, kwargs = {}) => {
    writeResult(session.session_id, action, kwargs);
    exit({exitCode: 0});
  };

  if (!sessions.length) {
    exit({exitCode: 0});
    return null;
  }

  if (screen === 'results') {
    return h(ResultsView, {
      onSelect: (idx) => {
        setCurrent(idx);
        setScreen('action');
      },
      onQuit: quit,
    });
  }

  if (screen === 'action') {
    return h(ActionView, {
      session,
      onBack: () => setScreen('results'),
      onDone: (action) => {
        if (['path', 'copy', 'export'].includes(action)) {
          // Run immediately, then show post-action choice inside ResultView
          finish(action);
        } else if (action === 'resume') setScreen('resume');
        else if (action === 'suppress_resume') setScreen('trim');
        else finish(action);
      },
    });
  }

  if (screen === 'resume') {
    return h(ResumeView, {
      onBack: () => setScreen('action'),
      onDone: (value) => {
        if (value === 'suppress_resume') setScreen('trim');
        else finish(value);
      },
    });
  }

  if (screen === 'trim') {
    return h(TrimForm, {
      onBack: () => setScreen('resume'),
      onSubmit: (opts) => finish('suppress_resume', opts),
      session,
    });
  }

  return null;
}

render(h(App));
