# Setup — Read This First

You are building the upstream pipeline only (Steps 1–3 of the AISO pipeline). This is the smaller, focused bundle for that.

## The 6 files in this bundle

**Inside `methodology/` folder:**

1. `README.md` — orientation
2. `pipeline-1.0.md` — the spec for Steps 1–3 (the most important file)
3. `versioning-1.0.md` — for hash-chaining prompts
4. `execution-1.0.md` — for the hexagonal seam pattern only

**At top level of your repo:**

5. `00_AGENT_KICKOFF_PROMPT.md` — paste into agent on day 1
6. `IMPLEMENTATION_BACKLOG_PHASE_12.md` — the 10-day work list

## Where to put them in your repo

```
your-aiso-project/
├── methodology/                           ← create this folder
│   ├── README.md
│   ├── pipeline-1.0.md
│   ├── versioning-1.0.md
│   └── execution-1.0.md
├── 00_AGENT_KICKOFF_PROMPT.md             ← top level
├── IMPLEMENTATION_BACKLOG_PHASE_12.md     ← top level
└── (your existing code)
```

## How to start the agent

1. Open your AI coding agent (Claude Code, Cursor, etc.) on your AISO project.
2. Open `00_AGENT_KICKOFF_PROMPT.md`, copy all of it.
3. Paste it as your first message to the agent.
4. The agent will read the spec files and say "I am ready to start." Reply: "Approved. Start 12.1."
5. The agent will do step 12.1 and show you the acceptance test output.
6. Review it. If good, reply: "Approved. Start 12.2." If not good, tell the agent what to fix.
7. Repeat until all 10 sub-steps are done (~10 working days of agent execution).

## What "good" looks like at each step

The agent should show you the acceptance test output at the end of each sub-step. Read it. If the test says PASS, approve. If FAIL, the agent fixes it before moving on. Don't approve a step unless its acceptance test passes.

## When to come back to me

- Agent says a step is impossible because the spec is wrong.
- Two specs conflict and you don't know which wins.
- Agent surfaces an edge case the spec didn't cover.
- You hit step 12.9 (founder-review checkpoint) and want help setting up the Slack notification.

Don't come back for routine coding questions — the agent handles those.

## When you finish Steps 1-3

After all 10 sub-steps pass, you'll have:
- A working onboarding flow that captures business context
- A crawler that fills in ~60% of fields automatically
- A question generator that produces 150 candidates
- A realism filter and scorer
- A selection algorithm that picks the best 50 questions
- A founder-review checkpoint before scans run

You will NOT have a working scan engine yet. That's the next phase (Phases 1–11 from the full backlog). Come back to me when you're ready for that.

## Realistic timeline

- Agent execution: ~10 working days (2 weeks)
- Your review time: ~30 minutes per sub-step = ~5 hours total
- Calendar time: ~2-3 weeks

Start the 200-question gold set work in parallel (see `methodology/pipeline-1.0.md` §C.4). That's manual work — you + 2 raters scoring questions on a 0–10 scale. Don't wait until you finish the code.
