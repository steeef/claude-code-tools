use std::env;
use std::process::{Command, Stdio};
mod shell;
use shell::Shell;

fn print_version() {
    println!("lmshell {}", env!("CARGO_PKG_VERSION"));
}

fn main() {
    // Tiny, predictable startup path:
    // - Handle trivial flags first to benchmark absolute minimal path
    // - Avoid any I/O before interactive mode (e.g., history, config)
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--version" | "-V" => {
                print_version();
                return;
            }
            // Execute and exit fast; used for startup benchmarks
            "-c" => {
                // Execute a one-off command for benchmarking and scripting
                if let Some(cmd) = args.next() {
                    let code = execute(&cmd);
                    std::process::exit(code);
                } else {
                    eprintln!("-c requires a command string");
                    std::process::exit(2);
                }
            }
            "-h" | "--help" => {
                println!(
                    "Usage: lmshell [OPTIONS]\n\n  -c <cmd>     Run command and exit (no-op)\n  -V, --version  Print version and exit\n  -h, --help     Show this help\n"
                );
                return;
            }
            _ => {}
        }
    }

    // Enter interactive loop with minimal setup.
    // Defer history/config I/O until after first successful line if desired.
    use rustyline::{error::ReadlineError, Editor};

    // Keep config defaults to minimize initialization work.
    let mut rl = Editor::<(), rustyline::history::DefaultHistory>::new().unwrap_or_else(|_| {
        Editor::<(), rustyline::history::DefaultHistory>::new().expect("editor")
    });

    // Start a persistent interactive shell in a PTY (aliases/functions/colors, one-time rc load)
    let mut pshell = match Shell::new() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Failed to start persistent shell: {e}");
            std::process::exit(1);
        }
    };

    let prompt = "lmshell> ";
    let mut history: Vec<(String, String)> = Vec::new(); // (user_input, generated_command)
    loop {
        match rl.readline(prompt) {
            Ok(line) => {
                let trimmed = line.trim();
                if trimmed == "exit" || trimmed == "quit" { break; }
                if !trimmed.is_empty() {
                    // Lazy-add to history after first non-empty line.
                    let _ = rl.add_history_entry(&line);
                }
                if trimmed.is_empty() {
                    continue;
                }

                // Natural language -> Claude -> suggested shell command
                match generate_command(trimmed, &history) {
                    Ok(suggested) => {
                        // Record history pair (user_input, generated_command)
                        history.push((trimmed.to_string(), suggested.clone()));
                        // Allow user to edit before execution
                        let edit_prompt = "cmd> ";
                        let edited = rl
                            .readline_with_initial(edit_prompt, (&suggested, ""))
                            .or_else(|_| rl.readline(edit_prompt));
                        match edited {
                            Ok(cmdline) => {
                                let cmd = cmdline.trim();
                                if cmd.is_empty() { continue; }
                                let _ = rl.add_history_entry(&cmdline);
                                match pshell.run(cmd) {
                                    Ok((_code, out)) => {
                                        if !out.is_empty() { 
                                            print!("{}", out);
                                            // Only add newline if output doesn't already end with one
                                            if !out.ends_with('\n') {
                                                println!();
                                            }
                                        }
                                    }
                                    Err(e) => eprintln!("exec error: {e}"),
                                }
                            }
                            Err(ReadlineError::Interrupted) | Err(ReadlineError::Eof) => break,
                            Err(err) => {
                                eprintln!("edit error: {err}");
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("Claude error: {}", e);
                        // Fallback: let user type a raw shell command
                        let fallback = rl.readline("cmd> ");
                        match fallback {
                            Ok(cmdline) => {
                                let cmd = cmdline.trim();
                                if cmd.is_empty() { continue; }
                                let _ = rl.add_history_entry(&cmdline);
                                match pshell.run(cmd) {
                                    Ok((_code, out)) => {
                                        if !out.is_empty() { 
                                            print!("{}", out);
                                            // Only add newline if output doesn't already end with one
                                            if !out.ends_with('\n') {
                                                println!();
                                            }
                                        }
                                    }
                                    Err(e) => eprintln!("exec error: {e}"),
                                }
                            }
                            Err(ReadlineError::Interrupted) | Err(ReadlineError::Eof) => break,
                            Err(err) => eprintln!("readline error: {err}"),
                        }
                    }
                }
            }
            Err(ReadlineError::Interrupted) | Err(ReadlineError::Eof) => break,
            Err(err) => {
                eprintln!("readline error: {err}");
                break;
            }
        }
    }
}

// --- Claude integration ---
fn generate_command(nl_prompt: &str, history: &[(String, String)]) -> Result<String, String> {
    // Build a prompt that includes full history and requests <COMMAND> markers
    let full_prompt = build_prompt_with_history(history, nl_prompt);

    let output = Command::new("claude")
        .arg("--model")
        .arg("sonnet")
        .arg("-p")
        .arg(&full_prompt)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("failed to spawn 'claude': {e}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("claude exited with status {}: {}", output.status, stderr.trim()));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    extract_command_from_output(&stdout)
        .ok_or_else(|| "could not extract a command from Claude output".to_string())
}

fn extract_command_from_output(s: &str) -> Option<String> {
    let trimmed = s.trim();
    if trimmed.is_empty() { return None; }

    // 1) First look for our custom markers <COMMAND>...</COMMAND>
    if let Some(start) = trimmed.find("<COMMAND>") {
        if let Some(end) = trimmed.find("</COMMAND>") {
            let cmd_start = start + 9; // length of "<COMMAND>"
            if cmd_start < end {
                let command = &trimmed[cmd_start..end];
                return Some(command.trim().to_string());
            }
        }
    }

    // 2) Try fenced code blocks (bash/sh or plain ```)
    if let Some(cmd) = extract_from_fence(trimmed) {
        return Some(cmd);
    }

    // 3) Look for a line beginning with '$ '
    for line in trimmed.lines() {
        let l = line.trim();
        if let Some(stripped) = l.strip_prefix("$ ") {
            let candidate = stripped.trim();
            if !candidate.is_empty() { return Some(candidate.to_string()); }
        }
    }

    // 4) Fallback: first non-empty, non-comment line that's not a greeting
    for line in trimmed.lines() {
        let l = line.trim();
        // Skip greetings and explanations
        if l.starts_with("Hello") || l.starts_with("Here") || l.contains("command to") {
            continue;
        }
        if l.is_empty() || l.starts_with('#') { continue; }
        return Some(l.to_string());
    }

    None
}

fn build_prompt_with_history(history: &[(String, String)], nl_prompt: &str) -> String {
    let mut buf = String::new();
    buf.push_str(
        "You are a shell command generator. Return ONLY the shell command wrapped in <COMMAND></COMMAND>. No prose.\nIf multiple steps are needed, join with '&&'.\n\nPrevious conversation:\n",
    );

    // Limit to the last 10 exchanges to bound prompt size
    let start = history.len().saturating_sub(10);
    for (user, cmd) in &history[start..] {
        buf.push_str("User: ");
        buf.push_str(user);
        buf.push('\n');
        buf.push_str("Command: <COMMAND>");
        buf.push_str(cmd);
        buf.push_str("</COMMAND>\n");
    }

    buf.push_str("\nUser: ");
    buf.push_str(nl_prompt);
    buf.push_str("\nGenerate command with <COMMAND></COMMAND> markers.");

    buf
}

fn extract_from_fence(s: &str) -> Option<String> {
    let mut lines = s.lines().peekable();
    while let Some(line) = lines.next() {
        let l = line.trim_start();
        if let Some(lang) = l.strip_prefix("```") {
            // Found a fence start. Optionally contains language like bash/sh.
            let is_shell = lang.contains("bash") || lang.contains("sh");
            let mut block = String::new();
            while let Some(content) = lines.next() {
                if content.trim_start().starts_with("```") { break; }
                block.push_str(content);
                block.push('\n');
            }
            if is_shell || !block.trim().is_empty() {
                // Clean leading '$ ' prompts per line.
                let cleaned = block
                    .lines()
                    .map(|ln| ln.strip_prefix("$ ").unwrap_or(ln))
                    .collect::<Vec<_>>()
                    .join("\n");
                let out = cleaned.trim();
                if !out.is_empty() { return Some(out.to_string()); }
            }
        }
    }
    None
}

// --- Shell execution ---
fn execute(cmd: &str) -> i32 {
    #[cfg(windows)]
    let status = Command::new("cmd").arg("/C").arg(cmd).status();

    #[cfg(not(windows))]
    let status = {
        // Use user's shell - temporarily back to simple -c
        let shell = env::var("SHELL").unwrap_or_else(|_| "/bin/sh".to_string());
        
        Command::new(&shell)
            .arg("-c")
            .arg(cmd)
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .status()
    };

    match status {
        Ok(s) => s.code().unwrap_or_default(),
        Err(e) => {
            eprintln!("failed to execute command: {e}");
            127
        }
    }
}
