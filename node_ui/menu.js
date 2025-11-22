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
  const id = (session.session_id || '').slice(0, 8).padEnd(8, ' ');
  const branch = session.branch ? chalk.cyan(` ${session.branch}`) : '';
  const preview = session.preview || '';
  const maxPreview = Math.max(0, width - 30);
  const trimmedPreview = preview.length > maxPreview
    ? preview.slice(0, maxPreview - 1) + '…'
    : preview;
  return h(
    Box,
    {flexDirection: 'column'},
    h(
      Text,
      {
        color: active ? 'black' : 'white',
        backgroundColor: active ? 'cyan' : undefined,
      },
      `${active ? figures.pointer : ' '} ${index + 1}. [${session.agent_display}] ${id} ${session.project}${branch}`
    ),
    preview
      ? h(Text, {dimColor: true}, trimmedPreview)
      : null
  );
}

function ResultsView({onSelect, onQuit}) {
  const [index, setIndex] = useState(0);
  const {stdout} = useStdout();
  const width = stdout?.columns || 80;

  useInput((input, key) => {
    if (key.escape) return onQuit();
    if (key.return) return onSelect(index);
    if (key.upArrow || input === 'k') setIndex((i) => Math.max(0, i - 1));
    if (key.downArrow || input === 'j') setIndex((i) => Math.min(sessions.length - 1, i + 1));
    const num = Number(input);
    if (!Number.isNaN(num) && num >= 1 && num <= sessions.length) {
      setIndex(num - 1);
      onSelect(num - 1);
    }
  });

  const kw = keywords.join(', ');
  const kwTrim = kw.length > width - 15 ? kw.slice(0, width - 18) + '…' : kw;

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
      sessions.map((s, i) =>
        h(SessionRow, {
          key: s.session_id,
          session: s,
          active: i === index,
          index: i,
          width,
        })
      )
    ),
    h(
      Box,
      {marginTop: 1},
      h(Text, {dimColor: true}, 'Enter: actions  Esc: quit  ↑/↓ or j/k: move  number: jump')
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
    h(Text, null, chalk.bgCyan.black(' Actions '), ' ', session.project),
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

function ResumeView({onBack, onDone}) {
  useInput((input, key) => {
    if (key.escape) onBack();
  });
  return h(
    Box,
    {flexDirection: 'column'},
    h(Text, null, chalk.bgGreen.black(' Resume options ')),
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
    h(Text, null, chalk.bgYellow.black(' Trim options ')),
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
  const [screen, setScreen] = useState('results');
  const [current, setCurrent] = useState(0);
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
        if (action === 'resume') setScreen('resume');
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
    });
  }

  return null;
}

render(h(App));
