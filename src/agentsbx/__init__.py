"""A gVisor-isolated container an LLM agent drives through tools.

The implementation lives in `.sandbox`; this re-exports the public surface so
callers can write `from agentsbx import Sandbox`. Private helpers
(`_truncate`) are deliberately not re-exported - import them from
`agentsbx.sandbox` if you need them, as the tests do.
"""

from .sandbox import (
    DEFAULT_IMAGE,
    MAX_OUTPUT_BYTES,
    Command,
    Sandbox,
    SandboxError,
    ShellResult,
)

__all__ = [
    "DEFAULT_IMAGE",
    "MAX_OUTPUT_BYTES",
    "Command",
    "Sandbox",
    "SandboxError",
    "ShellResult",
]
