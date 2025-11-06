# LM Studio Structured Output Mirror

**ELI5:** This is a tiny server that sits in front of your local LM Studio chat endpoint. When you ask a model for JSON, some open-source models ignore the “structured output” setting. This mirror quietly rewrites your request so the model follows your JSON Schema, then it checks the response and fixes the JSON if needed. You keep using the normal `/v1/chat/completions` API.

Humble truth: this is a pragmatic patch, not a silver bullet. It improves compliance for `gpt-oss-20b` and `gpt-oss-120b`. It cannot guarantee perfect output for every prompt or schema.

---

## What it does

- Detects when the request targets **open-source OSS models** that often ignore `response_format`.
- Moves your **JSON Schema** out of `response_format` and **injects it at the start of the user prompt**:
  - “The output will be in JSON following this schema: …”
  - “After thinking, output only the JSON according to this schema.”
- Sends to your **LM Studio** chat endpoint.
- **Validates** the returned text against your schema. If invalid, asks the model once to **repair** the JSON and returns the repaired result.
- Behaves like the **OpenAI** `/v1/chat/completions` API for clients.

---

## When to use this

- You rely on **structured JSON** from OSS chat models in LM Studio.
- Your client already sends `response_format: { type: "json_schema", json_schema: { ... } }`.
- You want to keep your client code unchanged.

---

## Requirements

- Python 3.9+
- LM Studio or another server that exposes `/v1/chat/completions` locally.

---

## Install

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
