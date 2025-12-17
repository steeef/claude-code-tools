# Running Claude Code with Local LLMs

This guide covers running Claude Code with local models using
[llama.cpp](https://github.com/ggml-org/llama.cpp)'s server, which provides an
Anthropic-compatible `/v1/messages` endpoint for certain supported models. The
models documented here have been tested to work with this endpoint.

## When to Use Local Models

These local models (20B-80B parameters) are not intended for complex coding tasks
where frontier models like Claude Opus excel. However, they are well-suited for
scenarios where privacy, offline access, or cost considerations are paramount:

- **Sensitive documents**: Working with confidential, proprietary, or classified
  materials that cannot be sent to external APIs
- **Personal knowledge management**: Querying your own private notes, journals,
  or research without data leaving your machine
- **Air-gapped environments**: Operating in secure facilities without internet
  access
- **Non-coding tasks**: Summarization, analysis, Q&A, and general text
  processing where model capability requirements are lower
- **Cost-sensitive workflows**: High-volume tasks where API costs would be
  prohibitive
- **Experimentation**: Testing prompts and workflows before committing to API
  usage

For production coding assistance, complex reasoning, or tasks requiring frontier
model capabilities, use Claude Code with the standard Anthropic API.

## Prerequisites

- [llama.cpp](https://github.com/ggml-org/llama.cpp) built and `llama-server`
  available in your PATH
- Sufficient RAM (64GB+ recommended for 30B+ models)
- Models will be downloaded automatically from HuggingFace on first run

## Shell Function for Claude Code

Add this function to your `~/.zshrc` or `~/.bashrc`:

```bash
cclocal() {
    local port=8123
    if [[ "$1" =~ ^[0-9]+$ ]]; then
        port="$1"
        shift
    fi
    (
        export ANTHROPIC_BASE_URL="http://127.0.0.1:${port}"
        claude "$@"
    )
}
```

Usage:

```bash
cclocal              # Connect to localhost:8123
cclocal 8124         # Connect to localhost:8124
cclocal 8124 --resume abc123  # With additional claude args
```

## Model Commands

### GPT-OSS-20B (Fast, Good Baseline)

Uses the built-in preset with optimized settings:

```bash
llama-server --gpt-oss-20b-default --port 8123 -a claude-opus-4-5
```

**Performance:** ~17-38 tok/s generation on M1 Max

### Qwen3-30B-A3B

```bash
llama-server -hf unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF \
  --port 8124 \
  -c 131072 \
  -b 32768 \
  -ub 1024 \
  --parallel 1 \
  --jinja \
  --chat-template-file ~/Git/llama.cpp/models/templates/Qwen3-Coder.jinja \
  -a claude-opus-4-5
```

**Performance:** ~15-27 tok/s generation on M1 Max

### Qwen3-Coder-30B-A3B (Recommended)

Uses the built-in preset with Q8_0 quantization (higher quality):

```bash
llama-server --fim-qwen-30b-default --port 8127 -a claude-opus-4-5
```

Downloads `ggml-org/Qwen3-Coder-30B-A3B-Instruct-Q8_0-GGUF` automatically on first
run.

### Qwen3-Next-80B-A3B (Better Long Context)

Newer SOTA model. Slower generation but performance doesn't degrade as much
with long contexts:

```bash
llama-server -hf unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:Q4_K_XL \
  --port 8126 \
  -c 131072 \
  -b 32768 \
  -ub 1024 \
  --parallel 1 \
  --jinja \
  -a claude-opus-4-5
```

**Performance:** ~5x slower generation than Qwen3-30B-A3B, but better on long
contexts

### Nemotron-3-Nano-30B-A3B (NVIDIA Reasoning Model)

```bash
llama-server -hf unsloth/Nemotron-3-Nano-30B-A3B-GGUF:Q4_K_XL \
  --port 8125 \
  -c 131072 \
  -b 32768 \
  -ub 1024 \
  --parallel 1 \
  --jinja \
  --chat-template-file ~/Git/llama.cpp/models/templates/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16.jinja \
  --temp 0.6 \
  --top-p 0.95 \
  --min-p 0.01 \
  -a claude-opus-4-5
```

**Recommended settings (from NVIDIA):**

- Tool calling: `temp=0.6`, `top_p=0.95`
- Reasoning tasks: `temp=1.0`, `top_p=1.0`

## Quick Reference

| Model | Port | Command |
|-------|------|---------|
| GPT-OSS-20B | 8123 | `llama-server --gpt-oss-20b-default --port 8123 -a claude-opus-4-5` |
| Qwen3-30B-A3B | 8124 | See full command above |
| Nemotron-3-Nano | 8125 | See full command above |
| Qwen3-Next-80B | 8126 | See full command above |
| Qwen3-Coder-30B | 8127 | `llama-server --fim-qwen-30b-default --port 8127 -a claude-opus-4-5` |

## Usage

1. Start the llama-server with your chosen model (first request will be slow
   while model loads)
2. In another terminal, run `cclocal <port>` to start Claude Code
3. Use Claude Code as normal

## Notes

- First request is slow while the model loads into memory (~10-30 seconds
  depending on model size)
- Subsequent requests are fast
- The `-a claude-opus-4-5` flag aliases the model name for compatibility
- The `/v1/messages` endpoint in llama-server handles Anthropic API translation
  automatically
- Each model's chat template handles the model-specific prompt formatting

## Troubleshooting

**"failed to find a memory slot" errors:**

Increase context size (`-c`) or reduce parallel slots (`--parallel 1`). Claude
Code sends large system prompts (~20k+ tokens).

**Slow generation:**

- Increase batch size: `-b 32768`
- Reduce parallel slots: `--parallel 1`
- Check if model is fully loaded in RAM/VRAM

**Model not responding correctly:**

Ensure you're using the correct chat template for your model. The template
handles formatting the Anthropic API messages into the model's expected format.
