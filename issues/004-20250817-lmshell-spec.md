# lmshell - Natural Language Shell Interface Specification

## Overview

`lmshell` is a command-line tool that bridges natural language and shell
commands, allowing users to describe what they want to do in plain English and
get an editable shell command they can review and execute.

## Core Workflow

1. User runs: `lmshell "list files in decreasing order of size"`
2. The natural language is sent to `claude -p '...'` 
3. Claude returns a shell command (e.g., `ls -lhS`)
4. Command is displayed in an **editable interface**
5. User can modify the command if needed
6. User presses Enter to execute the actual command
7. Output is displayed in the terminal

## Key Features

### 1. Natural Language Processing
- Pass user input directly to `claude -p` with appropriate prompt engineering
- Include context about the current directory, OS, and shell type
- Request only the command, no explanation

### 2. Editable Command Interface
- Display the generated command in an editable text field
- Support standard text editing shortcuts (arrow keys, backspace, etc.)
- Show the command with syntax highlighting if possible
- Allow Ctrl+C to cancel without executing

### 3. Command Execution
- Execute the final command in the user's shell
- Stream output in real-time
- Preserve colors and formatting from command output
- Return proper exit codes

### 4. Safety Features
- Show dangerous commands (rm -rf, dd, etc.) with a warning
- Option to dry-run commands when possible
- History of generated and executed commands
- Ability to review command before execution

## Technology Stack Recommendation

### Performance Requirements
**Top Priority: Speed and Responsiveness**
- Startup time must be <20ms
- Command generation to editable display <2s (dominated by Claude API)
- Zero perceptible lag during editing
- Minimal memory footprint (<5MB)
- Instant command execution handoff

### Technology Choice: Rust with rustyline

#### Why Rust for Maximum Performance
1. **Zero runtime overhead** - No interpreter or VM startup
2. **Single static binary** - ~2-5MB, instant loading
3. **Direct system calls** - No abstraction layers
4. **Memory efficient** - ~1-2MB RAM usage
5. **Proven in CLI tools** - Used by nushell, starship, ripgrep, fd, etc.

#### Core Dependencies
```toml
[dependencies]
rustyline = "13.0"        # Line editing (same as nushell)
clap = "4.0"              # CLI argument parsing
tokio = { version = "1", features = ["full"] }  # Async runtime
serde_json = "1.0"        # JSON parsing
colored = "2.0"           # Colored output
which = "5.0"             # Find claude binary
shellexpand = "3.0"       # Expand ~ and env vars
```

#### Performance Comparison
| Technology | Startup Time | Memory Usage | Binary Size |
|------------|-------------|--------------|-------------|
| Rust       | <10ms       | 1-2MB        | 2-5MB       |
| Go         | ~20ms       | 5-10MB       | 5-10MB      |
| Python     | 50-200ms    | 20-30MB      | N/A         |
| Node.js    | 100-300ms   | 30-50MB      | N/A         |

### Architecture Overview

```rust
// Main flow - all in compiled code
fn main() -> Result<()> {
    // 1. Parse args (instant)
    let args = Args::parse();
    
    // 2. Call Claude (network bound)
    let command = generate_command(&args.query)?;
    
    // 3. Present editable interface (instant)
    let mut rl = Editor::<()>::new()?;
    let edited = rl.readline_with_initial("$ ", (&command, ""))?;
    
    // 4. Execute (handoff to shell)
    execute_command(&edited)?;
    
    Ok(())
}
```

## Implementation Plan

### Phase 1: Core Functionality (Week 1)
1. Set up Rust project with Cargo
2. Implement Claude API integration via subprocess
3. Add rustyline-based command editor
4. Implement command execution with proper stdio handling
5. Create release build pipeline for multiple platforms

### Phase 2: Performance Optimization (Week 2)
1. Profile and optimize startup time
2. Implement command caching for repeated queries
3. Add pre-compiled binary distribution
4. Optimize Claude API calls with streaming

### Phase 3: Enhanced Features (Week 3)
1. Add syntax highlighting with syntect
2. Implement persistent history with SQLite
3. Add safety checks without performance penalty
4. Create minimal configuration system

## File Structure
```
lmshell/
├── Cargo.toml       # Rust dependencies and metadata
├── src/
│   ├── main.rs      # Main entry point and CLI parsing
│   ├── claude.rs    # Claude API integration
│   ├── editor.rs    # Rustyline editor setup
│   ├── executor.rs  # Command execution with stdio
│   ├── safety.rs    # Fast pattern matching for dangerous commands
│   ├── history.rs   # SQLite-based history (optional)
│   └── config.rs    # Minimal config parsing
├── benches/
│   └── startup.rs   # Benchmark startup time
└── .cargo/
    └── config.toml  # Optimization flags
```

### Cargo.toml Configuration
```toml
[package]
name = "lmshell"
version = "0.1.0"
edition = "2021"

[dependencies]
rustyline = "13.0"
clap = { version = "4.0", features = ["derive"] }
tokio = { version = "1", features = ["process", "rt-multi-thread"] }
colored = "2.0"
which = "5.0"
shellexpand = "3.0"
anyhow = "1.0"

[profile.release]
opt-level = 3          # Maximum optimization
lto = true            # Link-time optimization
codegen-units = 1     # Single codegen unit for better optimization
strip = true          # Strip symbols for smaller binary
panic = "abort"       # Smaller binary, faster panic

[profile.release-small]
inherits = "release"
opt-level = "z"       # Optimize for size
```

## Usage Examples

### Basic Usage
```bash
# Simple file operations
lmshell "show all python files modified today"
# Generated: find . -name "*.py" -mtime -1
# [User can edit, then press Enter to execute]

# System information
lmshell "check disk usage of home directory"
# Generated: du -sh ~
# [User can edit, then press Enter to execute]
```

### Advanced Usage
```bash
# Complex operations
lmshell "find large log files and compress them"
# Generated: find /var/log -type f -size +100M -exec gzip {} \;
# [User reviews, possibly adds -name "*.log", then executes]

# Git operations
lmshell "show commits from last week with stats"
# Generated: git log --since="1 week ago" --stat
# [User can edit, then press Enter to execute]
```

## Rust Implementation Details

### Key Performance Techniques

1. **Minimal Dependencies**: Each dependency adds startup time
2. **Static Linking**: Everything compiled into single binary
3. **Lazy Initialization**: Only load what's needed
4. **Direct System Calls**: Use `std::process::Command` directly

### Sample Implementation

```rust
// main.rs - Complete minimal implementation
use anyhow::Result;
use clap::Parser;
use colored::*;
use rustyline::Editor;
use std::process::{Command, Stdio};

#[derive(Parser)]
#[command(name = "lmshell")]
#[command(about = "Natural language shell interface")]
struct Args {
    /// Natural language command description
    query: String,
    
    /// Skip editing and execute directly
    #[arg(short, long)]
    yes: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();
    
    // Generate command via Claude (only real latency here)
    let command = generate_command(&args.query)?;
    
    // Fast path: skip editing if --yes
    let final_command = if args.yes {
        command.clone()
    } else {
        // Interactive editing (instant display)
        let mut rl = Editor::<()>::new()?;
        rl.readline_with_initial("$ ", (&command, ""))?
    };
    
    // Execute with proper stdio handling
    execute(&final_command)?;
    
    Ok(())
}

fn generate_command(query: &str) -> Result<String> {
    let output = Command::new("claude")
        .arg("-p")
        .arg(format!("Generate ONLY a shell command for: {}. \
                     Output ONLY the command, no explanation.", query))
        .output()?;
    
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn execute(cmd: &str) -> Result<()> {
    Command::new("sh")
        .arg("-c")
        .arg(cmd)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()?;
    
    Ok(())
}
```

### Build Optimization

```bash
# Development build (fast compilation)
cargo build

# Release build (maximum performance)
cargo build --release

# Size-optimized build
cargo build --profile release-small

# Cross-compilation for distribution
cargo build --release --target x86_64-apple-darwin
cargo build --release --target aarch64-apple-darwin
cargo build --release --target x86_64-unknown-linux-gnu
```

## Configuration

### Minimal Config File: `~/.lmshell/config.toml`
```toml
# Keep config minimal for performance
[claude]
timeout_ms = 5000

[safety]
dangerous_patterns = ["rm -rf /", "dd if=", "> /dev/"]

[cache]
enabled = true
ttl_seconds = 3600
```

## Error Handling

1. **Claude API Errors**: Fall back to error message, allow retry
2. **Invalid Commands**: Show error, keep in edit mode
3. **Execution Errors**: Display stderr, return proper exit code
4. **Interrupt Handling**: Ctrl+C cancels current operation cleanly

## Testing Strategy

1. **Unit Tests**: 
   - Command generation parsing
   - Safety check validation
   - Configuration loading

2. **Integration Tests**:
   - Full workflow from input to execution
   - Claude API integration
   - Various shell commands

3. **UI Tests**:
   - Textual component testing
   - Keyboard input handling
   - Display rendering

## Future Enhancements

1. **Learning Mode**: Learn from user corrections to improve suggestions
2. **Snippets**: Save frequently used commands as snippets
3. **Batch Mode**: Process multiple natural language commands
4. **Shell Integration**: Direct integration as shell function
5. **Command Explanation**: Option to explain what a command does
6. **Undo/Redo**: In the editor interface
7. **Auto-completion**: For partial commands in edit mode

## Success Metrics

1. Command generation accuracy > 80%
2. User edit rate < 30% (most commands are correct)
3. Response time < 2 seconds for command generation
4. Zero dangerous commands executed without warning

## Performance Benchmarks

### Expected Performance Metrics
| Metric | Target | Notes |
|--------|--------|-------|
| Startup time | <10ms | Time to first prompt |
| Command display | <10ms | After Claude returns |
| Edit latency | 0ms | Native terminal speed |
| Total overhead | <20ms | Excluding Claude API |
| Binary size | <5MB | Stripped release build |
| Memory usage | <2MB | Resident set size |

### Benchmark Script
```rust
// benches/startup.rs
use criterion::{criterion_group, criterion_main, Criterion};
use std::process::Command;

fn benchmark_startup(c: &mut Criterion) {
    c.bench_function("lmshell startup", |b| {
        b.iter(|| {
            Command::new("./target/release/lmshell")
                .arg("--help")
                .output()
                .unwrap();
        });
    });
}

criterion_group!(benches, benchmark_startup);
criterion_main!(benches);
```

## Dependencies

### Build Requirements
- Rust 1.70+ (for modern optimizations)
- Cargo (comes with Rust)
- claude CLI (must be installed and configured)

### Runtime Requirements
- claude CLI in PATH
- POSIX-compliant shell (/bin/sh)
- Terminal with standard ANSI support

## Development Timeline

- Day 1-2: Core Rust implementation with rustyline
- Day 3: Claude integration and command execution  
- Day 4: Performance optimization and benchmarking
- Day 5: Cross-platform builds and testing
- Day 6-7: Documentation and distribution setup

## Open Questions

1. Should we support multiple LLM backends beyond Claude?
2. How to handle commands that require sudo?
3. Should we integrate with shell history directly?
4. How to handle interactive commands (like vim, less)?
5. Should we support command chaining and pipes in edit mode?