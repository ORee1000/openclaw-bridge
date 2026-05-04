# OpenClaw Bridge

MCP Server connecting [Hermes Agent](https://github.com/NousResearch/hermes-agent) to **OpenClaw**, enabling Hermes to delegate tasks to OpenClaw agents.

## Architecture

```
Hermes (MCP client)
  │
  ├── call_openclaw(task)        → Kratos (full-persona agent, all tools)
  └── delegate_to_servant(task)  → task-servant (no-persona execution unit)
         │
         ▼
    OpenClaw Bridge (MCP Server :8765)
         │
         ▼  queue file
    OpenClaw Cron Worker
         │
         ▼  sessions_spawn
    OpenClaw Agent → executes → writes result
         │
         ▼  result file
    Bridge polls → returns to Hermes
```

## Quick Start

### 1. Install Dependencies

```bash
pip install mcp fastapi uvicorn
```

### 2. Start the Bridge

```bash
python bridge_server.py
# → MCP endpoint at http://127.0.0.1:8765/mcp
```

Environment variables (optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `BRIDGE_HOST` | `127.0.0.1` | Listen address |
| `BRIDGE_PORT` | `8765` | Listen port |
| `BRIDGE_QUEUE_DIR` | `~/.openclaw/workspace/bridge/queue` | Task queue directory |
| `BRIDGE_RESULTS_DIR` | `~/.openclaw/workspace/bridge/results` | Results directory |

### 3. Configure Hermes

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  openclaw-bridge:
    url: "http://127.0.0.1:8765/mcp"
    timeout: 360
    connect_timeout: 30
```

Restart Hermes gateway. Hermes will discover two new tools: `call_openclaw` and `delegate_to_servant`.

### 4. Set Up OpenClaw Cron Worker

On the OpenClaw side, create a cron job that polls the queue directory:

```
Schedule: every 30 seconds
Action: Read queue/*.json → sessions_spawn with correct agentId → write result
```

The OpenClaw config needs two agents:

```json
{
  "agents": {
    "list": [
      {
        "id": "hermes-servant",
        "model": "...",
        "subagents": { "allowAgents": ["task-servant"] }
      },
      {
        "id": "task-servant",
        "model": "...",
        "systemPromptOverride": "You are a task execution unit. Reply in strict format: [状态] done/failed [结果] ..."
      }
    ]
  }
}
```

### 5. Auto-Start on Boot

```bash
# Add to crontab
@reboot sleep 10 && nohup python3 /path/to/bridge_server.py >> /path/to/server.log 2>&1 &
```

## MCP Tools

### `call_openclaw(task, timeout=300)`

Delegate to the main OpenClaw agent (Kratos). Full persona, all tools available (browser, image/video generation, code execution, web search, file ops, TTS). Use for creative or complex tasks.

### `delegate_to_servant(task, timeout=300)`

Delegate to a minimal execution unit. No personality, strictly formatted output. Use for background data processing or mechanical tasks.

## Task Queue Protocol

Tasks are JSON files written to `QUEUE_DIR`:

```json
{
  "task_id": "abc123def456",
  "task": "The task description",
  "target_agent": "hermes-servant | task-servant",
  "timeout": 300,
  "status": "pending"
}
```

Results are JSON files written to `RESULTS_DIR`:

```json
{
  "task_id": "abc123def456",
  "status": "done | failed | need_confirm",
  "result": "The output from OpenClaw"
}
```

## License

MIT
