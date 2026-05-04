#!/usr/bin/env python3
"""
OpenClaw Bridge — MCP Server connecting Hermes Agent to OpenClaw.

Exposes two tools via StreamableHTTP (MCP protocol):
  - call_openclaw(task, timeout)      → Routes to the main OpenClaw agent (Kratos).
  - delegate_to_servant(task, timeout) → Routes to a minimal task-execution agent.

Hermes connects to this server as an MCP tool provider. When Hermes
invokes a tool, the bridge queues the task for OpenClaw, polls for the
result, and returns it to Hermes.

Requirements
------------
Python 3.10+, plus:
  pip install mcp fastapi uvicorn

Quick Start
-----------
  python bridge_server.py
  # → MCP endpoint at http://127.0.0.1:8765/mcp

Then configure Hermes (config.yaml):
  mcp_servers:
    openclaw-bridge:
      url: "http://127.0.0.1:8765/mcp"
      timeout: 360
      connect_timeout: 30

On the OpenClaw side, set up a cron worker that reads tasks from the
queue directory and writes results.
"""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# ── Configuration ──────────────────────────────────────────────────────────

QUEUE_DIR = Path(os.environ.get(
    "BRIDGE_QUEUE_DIR",
    os.path.expanduser("~/.openclaw/workspace/bridge/queue")
))
RESULTS_DIR = Path(os.environ.get(
    "BRIDGE_RESULTS_DIR",
    os.path.expanduser("~/.openclaw/workspace/bridge/results")
))

QUEUE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── MCP Server ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    "OpenClaw Bridge",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)

# ── Task Queue Helpers ─────────────────────────────────────────────────────

def _write_task(task: str, target_agent: str, timeout: int = 300) -> str:
    task_id = uuid.uuid4().hex[:12]
    task_file = QUEUE_DIR / f"{task_id}.json"
    payload = {
        "task_id": task_id,
        "task": task,
        "target_agent": target_agent,
        "timeout": timeout,
        "created_at": time.time(),
        "status": "pending",
    }
    task_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return task_id


def _wait_for_result(task_id: str, timeout: int = 300) -> dict:
    result_file = RESULTS_DIR / f"{task_id}.json"
    deadline = time.time() + timeout
    poll_interval = 1.0

    while time.time() < deadline:
        if result_file.exists():
            try:
                result = json.loads(result_file.read_text())
                result_file.unlink(missing_ok=True)
                queue_file = QUEUE_DIR / f"{task_id}.json"
                queue_file.unlink(missing_ok=True)
                return result
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(poll_interval)
        poll_interval = min(poll_interval * 1.2, 5.0)

    queue_file = QUEUE_DIR / f"{task_id}.json"
    queue_file.unlink(missing_ok=True)
    return {
        "status": "timeout",
        "result": f"No response from OpenClaw within {timeout}s.",
    }


def _format_result(result: dict) -> str:
    if result.get("status") == "timeout":
        return f"[TIMEOUT] {result.get('result', 'No response.')}"
    status = result.get("status", "unknown")
    output = result.get("result", "")
    if status == "done":
        return output
    if status == "failed":
        return f"[FAILED] {output}"
    if status == "need_confirm":
        return f"[NEEDS CONFIRMATION] {output}"
    return f"[{status.upper()}] {output}"


# ── MCP Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
async def call_openclaw(task: str, timeout: int = 300) -> str:
    """Delegate a task to Kratos — the main OpenClaw agent with full persona and tools.

    Kratos has: browser automation, image/video generation, file operations,
    code execution, web search, TTS, and more.

    Use for tasks needing creative thinking, complex reasoning, or human interaction.

    Args:
        task: Task description. Be specific and detailed.
        timeout: Max seconds to wait (default 300).

    Returns:
        Result from Kratos after task execution.
    """
    task_id = _write_task(task, target_agent="hermes-servant", timeout=timeout)
    result = await asyncio.to_thread(_wait_for_result, task_id, timeout)
    return _format_result(result)


@mcp.tool()
async def delegate_to_servant(task: str, timeout: int = 300) -> str:
    """Delegate a task to the task-servant — a minimal, no-persona execution unit.

    Returns strictly formatted output:
      [状态] done / failed / need_confirm
      [结果] <pure factual report>

    Use for background execution, data processing, or any task where you
    don't need personality — just results.

    Args:
        task: Task description. Be specific and detailed.
        timeout: Max seconds to wait (default 300).

    Returns:
        Formatted result from the task-servant.
    """
    task_id = _write_task(task, target_agent="task-servant", timeout=timeout)
    result = await asyncio.to_thread(_wait_for_result, task_id, timeout)
    return _format_result(result)


# ── Entry Point ────────────────────────────────────────────────────────────

def main():
    import uvicorn

    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "8765"))

    print(f"OpenClaw Bridge MCP Server — http://{host}:{port}/mcp")
    print(f"  call_openclaw(task, timeout)      → Kratos (full persona)")
    print(f"  delegate_to_servant(task, timeout) → task-servant (execution)")
    print(f"  Queue dir:  {QUEUE_DIR}")
    print(f"  Results dir: {RESULTS_DIR}")

    app = mcp.streamable_http_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
