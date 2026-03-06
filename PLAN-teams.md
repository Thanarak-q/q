# Q Team System — Implementation Plan

> **Status: IMPLEMENTED** — All core components are built and working. See `agent/team/` for the implementation.

## Overview

Multi-agent team system for Q. A **TeamLeader** orchestrator creates a task DAG, spawns **teammate agents** (each running in its own thread with its own Orchestrator), coordinates via a **shared TaskBoard + MessageBus**, and synthesizes results.

Teams are **opt-in** — single-agent mode remains the default and is unaffected.

---

## Architecture

```
User → chat_loop → /team or agentq --team
                        │
                  TeamLeader (thread 0)
                   ├── TaskBoard (shared)
                   ├── MessageBus (shared)
                   │
                   ├── Teammate "recon" (thread 1)
                   │     └── Orchestrator + ReconCallbacks
                   ├── Teammate "exploit" (thread 2)
                   │     └── Orchestrator + ExploitCallbacks
                   └── Teammate "analyst" (thread 3)
                         └── Orchestrator + AnalystCallbacks
```

Each teammate is an Orchestrator running in a thread (same pattern as `ParallelSolver`), but with:
- Its own **role-specific system prompt** and **skill injection**
- Access to a **shared TaskBoard** for coordination
- A **MessageBus** for sending updates to the lead and receiving instructions
- A **shared CostTracker** with pooled budget

---

## New Files

### 1. `agent/team/manager.py` — TeamManager

Creates/tracks/shuts down teams.

```python
@dataclass
class TeammateConfig:
    name: str           # "recon", "exploit", "analyst"
    role: str           # Human-readable role description
    model: str          # Model override (empty = default)
    max_steps: int      # Step budget for this agent
    prompt: str         # Role-specific prompt injected into system prompt
    skills: list[str]   # Extra skill categories to inject ("web", "pwn")

@dataclass
class TeamConfig:
    team_id: str
    challenge: str      # The challenge description
    category: str
    teammates: list[TeammateConfig]
    total_budget: float # Pooled $ budget
    created_at: str

class TeamManager:
    def __init__(self, config: AppConfig)
    def create_team(self, challenge: str, category: str, teammates: list[TeammateConfig]) -> TeamConfig
    def get_team(self, team_id: str) -> TeamConfig | None
    def list_teams() -> list[TeamConfig]
    def delete_team(self, team_id: str)
    # Persistence: ~/.q/teams/{team_id}.json
```

### 2. `agent/team/taskboard.py` — TaskBoard

Thread-safe shared task list (like Claude Code's TaskCreate/TaskList/TaskUpdate).

```python
@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str         # "pending" | "in_progress" | "completed" | "failed"
    owner: str          # Teammate name or "" (unassigned)
    blocked_by: list[str]  # Task IDs that must complete first
    result: str         # Output when completed
    created_at: float
    updated_at: float

class TaskBoard:
    """Thread-safe shared task list."""
    def __init__(self)
    def create(self, subject: str, description: str, blocked_by: list[str] = None) -> Task
    def get(self, task_id: str) -> Task | None
    def list_all(self) -> list[Task]
    def list_available(self) -> list[Task]  # pending, unblocked, unowned
    def claim(self, task_id: str, owner: str) -> bool
    def complete(self, task_id: str, result: str)
    def fail(self, task_id: str, reason: str)
    def to_dict(self) -> list[dict]  # For serialization
    # Internal: threading.Lock for all mutations
```

### 3. `agent/team/messages.py` — MessageBus

Thread-safe message passing between agents.

```python
@dataclass
class Message:
    sender: str         # "lead", "recon", "exploit", etc.
    recipient: str      # Target name or "*" for broadcast
    content: str
    msg_type: str       # "info" | "discovery" | "instruction" | "shutdown"
    timestamp: float

class MessageBus:
    """Thread-safe message queue per agent."""
    def __init__(self)
    def send(self, sender: str, recipient: str, content: str, msg_type: str = "info")
    def broadcast(self, sender: str, content: str, msg_type: str = "info")
    def receive(self, recipient: str) -> list[Message]  # Drains queue
    def has_messages(self, recipient: str) -> bool
    # Internal: dict[str, Queue] per recipient
```

### 4. `agent/team/leader.py` — TeamLeader

The lead orchestrator that manages the team lifecycle.

```python
class TeamLeader:
    def __init__(self, config: AppConfig, callbacks: AgentCallbacks)

    def solve_with_team(
        self,
        description: str,
        category: str,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
    ) -> SolveResult:
        """Full team lifecycle:
        1. Plan tasks based on challenge + category
        2. Select teammate roles (from TEAM_PRESETS or LLM-generated)
        3. Create TaskBoard + MessageBus
        4. Spawn teammate threads
        5. Monitor progress (poll task board + message bus)
        6. When flag found or all tasks done: cancel remaining, collect results
        7. Synthesize final answer
        8. Shutdown all teammates
        9. Return SolveResult
        """

    def _plan_tasks(self, description, category) -> list[dict]
        """Use LLM to break challenge into tasks. Returns task defs."""

    def _spawn_teammate(self, mate: TeammateConfig, taskboard, msgbus, cancel_event) -> Thread

    def _monitor_loop(self, taskboard, msgbus, threads, cancel_event) -> SolveResult
        """Poll for: flag found, all tasks complete, budget exhausted, timeout."""
```

### 5. `agent/team/callbacks.py` — TeamCallbacks

Callbacks implementation that forwards agent events to the MessageBus + TaskBoard.

```python
class TeamCallbacks(AgentCallbacks):
    """Callbacks for a teammate — forwards events to team infrastructure."""
    def __init__(self, name: str, msgbus: MessageBus, taskboard: TaskBoard)

    def on_flag_found(self, flag):
        self._msgbus.send(self._name, "lead", f"FLAG: {flag}", "discovery")

    def on_tool_result(self, tool_name, output, success):
        # Check if output contains useful discoveries, forward to lead

    def on_answer(self, answer, confidence, flag):
        self._msgbus.send(self._name, "lead", f"Answer: {answer}", "discovery")

    # ... other callbacks: minimal logging, no interactive UI
```

### 6. `agent/team/roles.py` — Preset Role Definitions

```python
TEAM_PRESETS: dict[str, list[TeammateConfig]] = {
    "web": [
        TeammateConfig(name="recon", role="Web reconnaissance", model="", max_steps=8,
            prompt="You are a web recon specialist. Enumerate endpoints, find hidden paths, analyze headers, identify technologies. Report all findings.",
            skills=["web"]),
        TeammateConfig(name="exploit", role="Exploit development", model="", max_steps=12,
            prompt="You are an exploit specialist. Use findings from recon to craft and execute exploits. Focus on getting the flag.",
            skills=["web"]),
    ],
    "pwn": [
        TeammateConfig(name="analyst", role="Binary analysis", model="", max_steps=8,
            prompt="You are a binary analyst. Run checksec, disassemble, identify vulnerabilities (BOF, format string, heap). Report offsets and protections.",
            skills=["pwn", "reverse"]),
        TeammateConfig(name="exploit", role="Exploit writer", model="", max_steps=12,
            prompt="You are a pwn exploit writer. Use the analyst's findings to write and test exploits with pwntools. Get the flag.",
            skills=["pwn"]),
    ],
    "crypto": [
        TeammateConfig(name="analyst", role="Crypto analysis", model="", max_steps=6,
            prompt="You are a cryptanalyst. Identify the cipher/scheme, find weaknesses, determine parameters. Report findings.",
            skills=["crypto"]),
        TeammateConfig(name="solver", role="Crypto solver", model="", max_steps=10,
            prompt="You are a crypto solver. Implement the attack based on the analyst's findings. Decrypt and get the flag.",
            skills=["crypto"]),
    ],
    # "forensics", "reverse", etc.
}
```

---

## Existing Files to Modify

### `config.py`
Add to `settings.json`:
```json
{
  "team_enabled": false,
  "team_max_agents": 3,
  "team_budget_multiplier": 2.0
}
```

### `ui/commands.py`
Add `/team` slash command:
```
/team                    — Show team status
/team start              — Start team solve on current challenge
/team stop               — Stop all teammates
/team tasks              — Show task board
/team messages           — Show message log
```

### `ui/chat.py`
- When user types a challenge and team mode is active, call `TeamLeader.solve_with_team()` instead of `Orchestrator.solve()`
- Show team activity via callbacks

### `ui/display.py`
Add `show_team_status()` method — shows a table of teammates (name, role, status, current task, steps, cost).

### `main.py`
Add `--team` CLI flag to enable team mode for that session.

### `README.md`
Add team section.

---

## Team Lifecycle Flow

```
1. User: "Solve this web challenge: ..."
   (team mode ON via --team or /team start)

2. TeamLeader._plan_tasks():
   → LLM call: "Break this challenge into 2-3 tasks for a team"
   → Returns: [
       {subject: "Recon: enumerate endpoints", desc: "..."},
       {subject: "Exploit: SQL injection on login", desc: "...", blocked_by: ["task_1"]},
     ]

3. TeamLeader creates TaskBoard with tasks
   → task_1: "Recon" (pending, unblocked)
   → task_2: "Exploit" (pending, blocked by task_1)

4. TeamLeader spawns teammates:
   → Thread "recon": Orchestrator(callbacks=TeamCallbacks("recon", ...))
   → Thread "exploit": Orchestrator(callbacks=TeamCallbacks("exploit", ...))

5. Teammate "recon":
   → Claims task_1 → status: in_progress
   → Runs Orchestrator.solve() with role-specific prompt
   → Finds: "/admin endpoint, SQLi in ?id= param"
   → Completes task_1 with result → unblocks task_2
   → Sends discovery message to lead

6. Teammate "exploit":
   → task_2 now unblocked → claims it
   → Gets recon results injected into prompt
   → Exploits SQLi → finds flag
   → Sends flag via MessageBus

7. TeamLeader._monitor_loop():
   → Sees flag in messages → sets cancel_event → all teammates stop
   → Collects results → returns SolveResult(success=True, flags=[...])

8. UI shows team summary table
```

---

## How Agents Communicate

1. **Task results** — When a teammate completes a task, its result is stored on the TaskBoard. The next teammate's prompt gets injected with previous task results.

2. **Discovery messages** — Teammates send "discovery" messages to the lead via MessageBus when they find something important (endpoints, keys, vulnerabilities).

3. **Lead instructions** — Lead can send "instruction" messages to teammates (e.g., "focus on /admin endpoint").

4. **Flag broadcast** — When any agent finds a flag, it broadcasts via MessageBus. The monitor loop catches it and cancels all agents.

5. **Shutdown** — Lead sends "shutdown" type messages. Teammates check their inbox between iterations and stop gracefully.

---

## How the UI Shows Team Activity

In the chat loop, when team mode is active:

```
╭─ Team: web_20260301_142530 ─────────────────────────────╮
│ Agent    │ Role        │ Task              │ Step │ Cost │
│──────────│─────────────│───────────────────│──────│──────│
│ recon    │ Web recon   │ Enumerate endpoints│ 3/8  │$0.02│
│ exploit  │ Exploit     │ (blocked)          │ 0/12 │$0.00│
╰──────────────────────────────────────────────────────────╯
  [recon] Found: /api/v1/users, /admin (403), /backup.zip
  [recon] Task completed: "Recon: enumerate endpoints"
  [exploit] Started: "Exploit: SQL injection on /api/v1/users?id="
  [exploit] FLAG FOUND: flag{sql_injection_master}
```

This is rendered by `TeamCallbacks` forwarding events to the display.

---

## File Structure

```
agent/team/
├── __init__.py
├── manager.py        # TeamManager — create/track/delete teams
├── taskboard.py      # TaskBoard — thread-safe shared task list
├── messages.py       # MessageBus — thread-safe message queues
├── leader.py         # TeamLeader — main team orchestrator
├── callbacks.py      # TeamCallbacks — agent→team event forwarding
└── roles.py          # TEAM_PRESETS — role definitions per category
```

---

## Implementation Status

All core components implemented:

- [x] `taskboard.py` — TaskBoard (thread-safe, dependency DAG, assignee field)
- [x] `messages.py` — MessageBus (per-agent queues, shutdown protocol)
- [x] `roles.py` — TeammateConfig + TEAM_PRESETS for 7 categories (web, pwn, crypto, forensics, reverse, osint, misc)
- [x] `callbacks.py` — TeamCallbacks (forwards flags/discoveries/errors to MessageBus)
- [x] `leader.py` — TeamLeader (reactive coordinator, task DAG, graceful shutdown)
- [x] `manager.py` — TeamManager (persistence to ~/.q/teams/)
- [x] `ui/commands.py` — `/team` slash command (on/off/tasks/messages)
- [x] `ui/chat.py` — Team mode integration
- [x] `config.py` — Team settings (team_enabled, team_max_agents, team_task_timeout)
- [x] `main.py` — `--team` flag
- [x] `README.md` — Documentation

### Known gaps

- [ ] Missing `ai` category in TEAM_PRESETS
- [ ] No dedicated team tests
- [ ] TeamCallbacks.on_ask_user returns "" (teammates can't ask user)
