use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use std::env;
use std::io::{Read, Write};

const SENTINEL_PREFIX: &str = "<LMEND:";
const SENTINEL_SUFFIX: &str = ">";

pub struct Shell {
    #[allow(dead_code)]
    master: Box<dyn MasterPty + Send>,
    #[allow(dead_code)]
    child: Box<dyn Child + Send>,
    reader: Box<dyn Read + Send>,
    writer: Box<dyn Write + Send>,
}

impl Shell {
    pub fn new() -> Result<Self, String> {
        let shell_path = env::var("SHELL")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "/bin/zsh".to_string());

        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize {
                rows: 24,
                cols: 80,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(|e| format!("openpty failed: {e}"))?;

        let mut cmd = CommandBuilder::new(shell_path);
        // Login + interactive to ensure rc files load and aliases/functions are available
        cmd.arg("-l");
        cmd.arg("-i");
        cmd.env("TERM", env::var("TERM").unwrap_or_else(|_| "xterm-256color".into()));
        cmd.env("LMSHELL", "1");

        // Set the working directory to the current directory
        if let Ok(cwd) = env::current_dir() {
            cmd.cwd(cwd);
        }

        let child = pair
            .slave
            .spawn_command(cmd)
            .map_err(|e| format!("spawn shell failed: {e}"))?;

        // Parent doesn't need the slave end.
        drop(pair.slave);

        let reader = pair
            .master
            .try_clone_reader()
            .map_err(|e| format!("clone reader failed: {e}"))?;
        let writer = pair
            .master
            .take_writer()
            .map_err(|e| format!("take writer failed: {e}"))?;

        // Disable ZLE (zsh line editor) to prevent command echo and prompt repainting
        // Wait a moment for shell to initialize
        std::thread::sleep(std::time::Duration::from_millis(100));

        // Create a shell struct first
        let mut shell = Shell {
            master: pair.master,
            child,
            reader,
            writer,
        };

        // Disable ZLE and TTY echo to prevent command echo and prompt repainting
        // This keeps aliases/functions from .zshrc but stops prompt repainting and TTY echo
        // -echonl also suppresses echoing of newlines
        let _ = shell.run("unsetopt zle; unsetopt prompt_cr; PS1=''; stty -echo -echonl");

        Ok(shell)
    }

    // Runs a command in the persistent shell, returning (exit_code, output)
    // Simple implementation: write the command + sentinel, then read until the sentinel is observed.
    pub fn run(&mut self, cmd: &str) -> Result<(i32, String), String> {
        // Append a sentinel that prints to the TTY to avoid being captured by pipes/redirections.
        // Use a distinctive marker that's unlikely to appear in normal output.
        let to_send = format!(
            "{}; printf '{}%d{}\\n' $? > /dev/tty\r",
            cmd, SENTINEL_PREFIX, SENTINEL_SUFFIX
        );

        self.writer
            .write_all(to_send.as_bytes())
            .map_err(|e| format!("write to pty failed: {e}"))?;
        self.writer
            .flush()
            .map_err(|e| format!("flush pty failed: {e}"))?;

        let mut buf = Vec::with_capacity(4096);
        let mut tmp = [0u8; 4096];
        let mut exit_code: Option<i32> = None;
        let mut sent_start: Option<usize> = None;

        loop {
            let n = self
                .reader
                .read(&mut tmp)
                .map_err(|e| format!("read from pty failed: {e}"))?;
            if n == 0 {
                // EOF; shell died?
                break;
            }
            buf.extend_from_slice(&tmp[..n]);
            if let Some((s, _e, code)) = find_sentinel(&buf) {
                exit_code = Some(code);
                sent_start = Some(s);
                break;
            }
        }

        let exit_code = exit_code.ok_or_else(|| "shell terminated before sentinel".to_string())?;
        let sent_start = sent_start.ok_or_else(|| "no sentinel found in output".to_string())?;

        // Output before sentinel is the command output
        let output_bytes = if buf.len() >= sent_start { &buf[..sent_start] } else { &buf[..] };
        let mut out = String::from_utf8_lossy(output_bytes).to_string();

        // Strip ANSI escape sequences and control characters
        out = strip_ansi_codes(&out);

        // Trim any trailing/leading whitespace
        out = out.trim().to_string();

        Ok((exit_code, out))
    }
}

fn strip_ansi_codes(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();

    while let Some(c) = chars.next() {
        if c == '\x1b' {
            // ESC character - start of ANSI sequence
            if chars.peek() == Some(&'[') {
                chars.next(); // consume '['
                // Skip until we find a letter (the command character)
                while let Some(&next_c) = chars.peek() {
                    chars.next();
                    if next_c.is_ascii_alphabetic() {
                        break;
                    }
                }
            } else if chars.peek() == Some(&']') {
                // OSC sequence (like terminal titles)
                chars.next(); // consume ']'
                // Skip until we find ESC \ or BEL
                while let Some(next_c) = chars.next() {
                    if next_c == '\x07' { // BEL
                        break;
                    }
                    if next_c == '\x1b' && chars.peek() == Some(&'\\') {
                        chars.next(); // consume '\'
                        break;
                    }
                }
            }
        } else if c == '\r' {
            // Skip carriage returns unless followed by something other than newline
            if chars.peek() != Some(&'\n') {
                // Standalone \r - treat as line clear, skip everything before it on this line
                // For simplicity, just skip the \r
                continue;
            }
            // \r\n together - keep just the \n (it will be added when we process \n)
        } else {
            result.push(c);
        }
    }

    result
}

fn find_sentinel(buf: &[u8]) -> Option<(usize, usize, i32)> {
    // Looks for <LMEND:NUM> pattern; returns (start_index, end_index_exclusive, num)
    let pre = SENTINEL_PREFIX.as_bytes();
    let suf = SENTINEL_SUFFIX.as_bytes()[0]; // '>'
    let hay = buf;
    let mut i = 0;
    while i + pre.len() < hay.len() {
        if hay[i..].starts_with(pre) {
            let start = i;
            // parse digits until '>'
            let mut j = i + pre.len();
            let mut val: i32 = 0;
            let mut has_digit = false;
            while j < hay.len() {
                let b = hay[j];
                if b == suf {
                    if has_digit {
                        let end = j + 1;
                        return Some((start, end, val));
                    } else {
                        break;
                    }
                } else if (b as char).is_ascii_digit() {
                    has_digit = true;
                    val = val.saturating_mul(10).saturating_add((b - b'0') as i32);
                    j += 1;
                } else {
                    break;
                }
            }
        }
        i += 1;
    }
    None
}
