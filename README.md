# LM Studio/llama.cpp Structured Output Mirror

It's been a known issue that structured output for GPT-OSS-20b and 120b is broken for LM Studio or anything that uses the GGUFs via llama.cpp. This is a (hopefully temporary) workaround that's a tiny server that sits in front of your local LM Studio chat endpoint and essentially moves the structured json schema from the response schema of the payload to the input prompt. 

While this mirror is running, you can use an alternate endpoint port 1235 (E.g, "http://localhost:1235/v1/chat/completions") to ask for a JSON output. This mirror rewrites your request so the model follows your JSON Schema, then it checks the response and fixes the JSON if needed. This is a pragmatic patch, and is not perfect. It brings GPT-OSS-20b JSON compliance from 0% gibberish to about 90% via the default test in the [LLM Structured JSON Tester](https://github.com/shihanqu/LLM-Structured-JSON-Tester)

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

- You rely on **structured JSON** from OSS chat models in LM Studio, Ollama, llama.cpp
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
