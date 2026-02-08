# Tracing Guide

This project now emits structured traces for all main runtime moments:
- HTTP request start/end
- API submit parsing and failures
- game engine submit/run turn phases
- OpenAI judge request/response parsing
- LLM-authoritative judgment (`engine.llm_judgment.done`), progression, and asset resolution

## Trace Output

- Default file: `logs/trace.ndjson`
- Default stdout: enabled
- Format: one JSON object per line

Each event contains:
- `ts`
- `level`
- `component` (`server`, `engine`, `openai_judge`, `assets`)
- `event`
- `trace_id`
- optional fields (`span_id`, `elapsed_ms`, payload snippets, errors)

## Config

Set in `.env` (or shell env):

```bash
TRACE_ENABLED=1
TRACE_STDOUT=1
TRACE_FILE=logs/trace.ndjson
TRACE_MAX_VALUE_LEN=300
```

## Quick Commands

Start server:

```bash
python3 server.py
```

Read recent events:

```bash
python3 scripts/trace_report.py --tail 120
```

Filter by request trace id:

```bash
python3 scripts/trace_report.py --trace-id <TRACE_ID>
```

Filter by component:

```bash
python3 scripts/trace_report.py --component openai_judge --tail 80
```

## How To Share Debug Context With Another Agent

1. Reproduce the bug once.
2. Copy `trace_id` from API response (also logged in browser console as `trace_id(submit)`).
3. Export focused trace:

```bash
python3 scripts/trace_report.py --trace-id <TRACE_ID> --tail 500
```

4. Share:
- trace output
- failing input text
- current game state (`/api/state` output)
- expected vs actual behavior
