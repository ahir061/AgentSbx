# AgentSbx

> **The secure, gVisor-isolated code execution sandbox for autonomous AI agents.**

AgentSbx provides autonomous LLM agents with shell access inside a dedicated, kernel-isolated environment: one [gVisor](https://gvisor.dev/)-isolated Docker container per session, driven entirely from the host by executing each command as an independent `docker exec`.

---

## Quickstart

```python
from agentsbx import Sandbox

with Sandbox() as sbx:
    sbx.shell_exec("python3 -m venv venv")  # runs in /root, the workspace
    sbx.shell_exec("/root/venv/bin/python --version")  # use absolute paths across calls
```

---

## Security Model & Threat Boundary

AgentSbx is designed around the threat model of a capable, potentially hostile AI agent. The boundary is enforced through layered isolation:

* **Kernel Isolation (`runsc`)**: The agent runs as root *inside* the container, but gVisor's Sentry runs deprivileged on the host. Container-root is **not** host-root.
* **Agent-Outside Architecture**: The evaluation harness and all LLM API keys remain on the host machine—never inside the container. This guarantees key custody, audit-log integrity, and artifact purity.
* **Air-Gapped Networking (`--network none`)**: The container has no network access. It cannot exfiltrate secrets, communicate with command-and-control servers, or attack external infrastructure.
* **Zero Host Mounts**: Nothing from the host filesystem is mounted in. The agent operates strictly inside `/root` (its workspace), and task dependencies are baked directly into the container image rather than fetched at runtime. Work results are extracted separately from the container.

---

## Execution Model: Stateless Commands, Durable Container

AgentSbx deliberately separates state into two distinct tiers:

| Tier | Lifecycle | Behavior |
| :--- | :--- | :--- |
| **Container** | Durable | Files, installed packages, and backgrounded processes persist for the entire lifetime of the sandbox. |
| **Shell Session** | Stateless | Working directory (`cwd`), exported environment variables, and shell functions do **not** persist between commands. |

### Why Stateless Commands?

Humans rely heavily on shell-session state (`cd`, `export`, `source activate`). Autonomous agents do not—an agent can emit absolute paths and chain commands (`cd src && make`). 

Dropping the persistent shell provides critical advantages:
* **No Sentinel Parsing**: Eliminates the fragile problem of detecting when a command finishes over a shared PTY stream. "Done" is simply the process exiting.
* **Direct Output Pipes**: Output streams directly from the process pipe with zero host-side files used for command text or output, removing that entire attack surface.
* **Failure Containment**: A syntax error or shell-fatal configuration (`set -e` followed by a failure) only terminates that specific command's process. There is no shared session to wedge, leaving subsequent commands unaffected.

### Non-Fatal Timeouts

When a command exceeds its timeout, AgentSbx does not treat it as an error. The process continues running in the background, and the agent receives the output accumulated so far. Because a slow test suite and a hung process look identical to a static timeout, the agent holds the partial logs and makes the judgment call: either keep waiting via `shell_wait` or terminate it via `shell_kill`.

---

## Configuration & Resource Limits

`Sandbox` accepts customizable parameters to control container sizing, execution defaults, and base images:

```python
from agentsbx import DEFAULT_IMAGE, Sandbox

with Sandbox(
    image=DEFAULT_IMAGE,  # "python:3.12" (includes buildpack-deps: gcc, make, etc.)
    memory="2g",  # Memory limit (--memory)
    cpus="2",  # CPU quota (--cpus)
    pids_limit=512,  # PID limit to prevent fork bombs (--pids-limit)
    exec_timeout=60,  # Default seconds to wait before reporting partial output
) as sbx:
    ...
```

---

## Agent Tool Interface

AgentSbx exposes three core tools to the model:

* **`shell_exec(command, timeout=None)`**  
  Executes a command inside the container from `/root`. If the timeout expires before completion, returns partial output while keeping the process running.
* **`shell_wait(timeout=None)`**  
  Continues waiting on a currently running command, returning incremental output produced since the last call.
* **`shell_kill()`**  
  Terminates the currently running command (attempting `SIGTERM` followed by `SIGKILL`).

Every tool executes strictly inside the container. No tool touches the host filesystem at paths chosen by the agent. Files are written via the shell, where quoted heredocs preserve content verbatim because commands are passed via argv rather than string interpolation.

### LLM Tool Schema & Dispatch

AgentSbx includes built-in support for tool-calling APIs (e.g. Anthropic Claude tool use):

* **`Sandbox.TOOLS`**: Pre-defined JSON schema array defining `shell_exec`, `shell_wait`, and `shell_kill`.
* **`sbx.dispatch(tool_name, tool_input)`**: Direct dispatcher routing tool use blocks to the corresponding sandbox method:

```python
# Provide TOOLS schema directly to the model
response = client.messages.create(
    model="claude-3-7-sonnet-20250219",
    tools=Sandbox.TOOLS,
    messages=messages,
)

# Dispatch tool call directly to sandbox
for block in response.content:
    if block.type == "tool_use":
        result_text = sbx.dispatch(block.name, block.input)
```

### Output Truncation & Structured Results

* **Output Truncation (`MAX_OUTPUT_BYTES = 30_000`)**: Single command outputs are capped at 30,000 characters to prevent build logs or infinite output loops from consuming the LLM context window. Truncation keeps the head and tail while trimming the middle.
* **Rendered Text vs. `ShellResult`**:
  * Tool methods (`shell_exec`, `shell_wait`, `shell_kill`, `dispatch`) return formatted strings rendered specifically for LLM context (e.g. `exit=0\noutput:\n...` or `still running after 3s...`).
  * The underlying runner (`sbx.runner.run(...)`, `sbx.runner.wait()`, `sbx.runner.kill()`) returns typed `ShellResult` objects containing `output`, `exit_code`, `status` (`completed`, `running`, `killed`, `rejected`), `note`, `elapsed`, and `idle` attributes.
  * Public exports from `agentsbx`: `Sandbox`, `Command`, `ShellResult`, `SandboxError`, `DEFAULT_IMAGE`, and `MAX_OUTPUT_BYTES`.

---

## Implementation Details (`src/agentsbx/sandbox.py`)

Each command is launched using the following wrapper:

```sh
docker exec ... bash -c 'echo "__PID__$$"; exec bash -c "$1" 2>&1' bash <command>
```

Key engineering decisions in this wrapper:
* **Argv Passing (`$1`)**: The command is passed as an isolated argument element rather than spliced into a shell string. Quotes, backslashes, and newlines require zero escaping.
* **Guaranteed PID Line**: `echo "__PID__$$"` executes before `exec` replaces the process image (preserving the PID). This PID is emitted as the guaranteed-first output line and stripped by the host reader before reaching the agent. `shell_kill` uses this PID to target process trees accurately without false positives.
* **In-Container Stderr Merging (`2>&1`)**: `docker exec` transports stdout and stderr as independent streams whose relative order is lost in transit. Merging them at the source inside the container preserves the true terminal interleaving.

---

## Requirements

* **Python `>=3.14`**: The package requires Python 3.14 or newer (`requires-python = ">=3.14"` in `pyproject.toml`).
* **Docker** installed with the gVisor runtime registered as `runsc`.
* **Docker Permissions**: The invoking user must belong to the `docker` group (no `sudo` required; start a new shell session after adding your user).
* **uv** (recommended): Used for package management, presubmit checks (`./scripts/check.sh`), and the `uv_build` backend.

---

## Verification & Presubmits

Run all presubmit checks in one command:

```sh
./scripts/check.sh
```

### Individual Quality Gates

#### Formatting & Linting
```bash
# Format code
uv run ruff format .

# Run lint checks with autofix
uv run ruff check --fix
```

#### Test Suite
The test suite is split into infrastructure-free logic tests and container-backed integration tests:

```bash
# Pure logic tests (~0.1s; runs anywhere without Docker or gVisor)
uv run pytest -m "not docker"

# Full test suite (~18s; requires Docker + gVisor)
uv run pytest
```

* **Logic tests (`tests/test_units.py`)**: Validate output truncation, result rendering, tool dispatch schemas, and error guards without launching containers.
* **Container tests (`tests/test_integration.py`)**: Tests marked `docker` automatically skip with an explanatory message if Docker or `runsc` is unavailable. To keep the suite under 20 seconds, container tests share a single session-scoped sandbox; because commands are stateless, the only cleanup needed between tests is terminating in-flight processes.

---

## License

MIT - see [LICENSE](LICENSE).
