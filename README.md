# AgentSbx

**Secure, gVisor-isolated code execution sandbox for autonomous AI Agents.**

Built by [Ahir](https://github.com/ahir061).

AgentSbx gives every autonomous AI agent its own personal sandbox: a dedicated, isolated environment with full shell access for executing code, using tools, and interacting with the filesystem.

Each session runs in its own [gVisor](https://gvisor.dev/)-sandboxed Docker container, while execution is controlled entirely from the host. Agent commands are run independently via `docker exec`, keeping the sandbox lifecycle and orchestration outside the container.


## Highlights

- **Kernel Isolation**: Runs under gVisor (`runsc`) so container-root cannot compromise the host.
- **Air-Gapped**: Starts with `--network none` and zero host mounts to prevent data exfiltration.
- **Stateless Commands**: Each command is an isolated `docker exec` process—no wedged shell sessions or fragile PTY sentinel parsing.
- **Durable Container**: Workspace files, installed packages, and background processes persist across calls.
- **Non-Fatal Timeouts**: Exceeded timeouts return partial logs while the process continues running.
- **LLM Tool Ready**: Ships with Anthropic-compatible tool schemas (`Sandbox.TOOLS`) and a dispatcher (`dispatch`).

## Quickstart

```python
from agentsbx import Sandbox

with Sandbox() as sbx:
    # Commands run from /root (the container workspace)
    print(sbx.shell_exec("python3 -m venv venv"))
    print(sbx.shell_exec("/root/venv/bin/python --version"))
```

## Agent Tools

AgentSbx exposes three core tools to the agent:

| Tool | Description |
| --- | --- |
| `shell_exec(command, timeout=60)` | Runs a command from `/root`. Returns exit code and output, or partial output if timed out. |
| `shell_wait(timeout=60)` | Keeps waiting on a running command and streams incremental output. |
| `shell_kill()` | Terminates the running command via `SIGTERM` followed by `SIGKILL`. |

### LLM Tool Dispatch

Pass `Sandbox.TOOLS` directly to models that support tool-calling and route invocations with `dispatch`:

```python
# Pass tools to model
response = client.messages.create(
    model="claude-3-7-sonnet-20250219",
    tools=Sandbox.TOOLS,
    messages=messages,
)

# Route tool calls to the sandbox
for block in response.content:
    if block.type == "tool_use":
        result = sbx.dispatch(block.name, block.input)
```

## Configuration

Customize resource limits and execution defaults:

```python
from agentsbx import Sandbox

with Sandbox(
    image="python:3.12",  # Default image (includes buildpack-deps: gcc, make)
    memory="2g",  # Memory limit
    cpus="2",  # CPU quota
    pids_limit=512,  # Process limit (guards against fork bombs)
    exec_timeout=60,  # Default command timeout in seconds
) as sbx:
    ...
```

## How It Works

Each command is launched as:

```sh
docker exec ... bash -c 'echo "__PID__$$"; exec bash -c "$1" 2>&1' bash <command>
```

- **Argv Passing (`$1`)**: Avoids string interpolation and quoting issues.
- **Guaranteed PID**: Extracts the bash PID on the first line for reliable process termination with `shell_kill`.
- **In-Container Stderr Merging (`2>&1`)**: Preserves true terminal interleaving of stdout and stderr.
- **Output Truncation**: Output exceeding `30,000` characters is truncated while preserving head and tail context.

## Requirements

- **Python `>=3.14`**
- **Docker** with the gVisor runtime (`runsc`) installed
- User added to the `docker` group
- **uv** for project and environment management

## Development

Run all presubmit checks (Ruff formatting, linting, and pytest):

```bash
./scripts/check.sh
```

Or run tests individually:

```bash
# Pure logic tests (runs anywhere without Docker/gVisor)
uv run pytest -m "not docker"

# Full test suite (requires Docker + gVisor)
uv run pytest
```

## License

MIT - see [LICENSE](LICENSE).
