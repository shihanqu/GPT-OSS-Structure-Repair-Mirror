
import json
import re
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from jsonschema import Draft7Validator, RefResolver, ValidationError

# ----- Configuration -----
UPSTREAM_URL = os.getenv("UPSTREAM_URL", "http://localhost:1234/v1/chat/completions")
TIMEOUT_SECS = float(os.getenv("TIMEOUT_SECS", "120"))
TARGET_MODELS = os.getenv("TARGET_MODELS", "openai/gpt-oss-20b,openai/gpt-oss-120b").split(",")
ALLOW_STREAM_REPAIR = os.getenv("ALLOW_STREAM_REPAIR", "false").lower() == "true"

# ----- Utilities -----

def _extract_schema_and_type(response_format: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not response_format or not isinstance(response_format, dict):
        return None
    # OpenAI styles: {"type":"json_schema","json_schema":{"name":"...","schema":{...}}}
    # or legacy: {"type":"json_object", "schema":{...}}
    t = response_format.get("type")
    if t == "json_schema":
        js = response_format.get("json_schema") or {}
        schema = js.get("schema")
        if isinstance(schema, dict):
            return schema
    elif t == "json_object":
        schema = response_format.get("schema")
        if isinstance(schema, dict):
            return schema
    return None

def _prepend_schema_instructions(messages: List[Dict[str, Any]], schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    instr = (
        "The output will be in JSON following this schema:\n\n"
        f"{schema_str}\n\n"
        "After thinking, output only the JSON according to this schema."
    )
    # Find last user message; prepend instructions to its content.
    idx = None
    for i in range(len(messages)-1, -1, -1):
        if messages[i].get("role") == "user":
            idx = i
            break
    if idx is not None:
        original = messages[idx].get("content", "")
        messages[idx]["content"] = instr + "\n\n" + str(original)
        return messages
    # Fallback: add a system message at start.
    return [{"role": "system", "content": instr}] + messages

def _strip_code_fences(text: str) -> str:
    # Remove ```json ... ``` or ``` ... ``` fences
    fenced = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.MULTILINE)
    m = fenced.search(text.strip())
    if m:
        return m.group(1).strip()
    return text.strip()

def _try_json_loads(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        # Attempt minimal fixes: remove trailing commas and convert single quotes if it looks like JSON-ish
        fixed = re.sub(r",\s*([}\]])", r"\1", text)  # trailing commas
        fixed = fixed.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        # naive single-quote to double-quote when it looks safe
        if fixed.count('"') < 2 and "'" in fixed:
            fixed = re.sub(r"'", '"', fixed)
        try:
            return json.loads(fixed)
        except Exception:
            return None

def _validate_against_schema(obj: Any, schema: Dict[str, Any]) -> Optional[str]:
    try:
        Draft7Validator(schema).validate(obj)
        return None
    except ValidationError as e:
        return str(e)

async def _repair_with_model(raw_text: str, schema: Dict[str, Any], client: httpx.AsyncClient, original_payload: Dict[str, Any]) -> Optional[str]:
    """Ask the upstream model to repair the JSON by providing a repair prompt."""
    repair_prompt = [
        {
            "role": "user",
            "content": (
                "Repair the following JSON so that it is valid and fully conforms to this JSON Schema. "
                "Output only the repaired JSON and nothing else.\n\n"
                "Schema:\n"
                f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
                "JSON to repair:\n"
                f"{raw_text}"
            ),
        }
    ]
    payload = {k: v for k, v in original_payload.items() if k not in ("messages", "response_format", "stream")}
    payload.update({"messages": repair_prompt, "stream": False})
    try:
        r = await client.post(UPSTREAM_URL, json=payload, timeout=TIMEOUT_SECS)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception:
        return None

def _shape_response_like_openai(upstream_json: Dict[str, Any], new_content: str) -> Dict[str, Any]:
    out = dict(upstream_json)
    # Replace the first choice content and clear refusal fields if present
    if "choices" in out and out["choices"]:
        out["choices"][0] = dict(out["choices"][0])
        msg = dict(out["choices"][0].get("message", {}))
        msg["content"] = new_content
        out["choices"][0]["message"] = msg
        if "finish_reason" in out["choices"][0]:
            out["choices"][0]["finish_reason"] = out["choices"][0]["finish_reason"]
    return out

# ----- FastAPI app -----

app = FastAPI(title="LM Studio Structured Output Mirror", version="1.0.0")

class ChatRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    response_format: Optional[Dict[str, Any]] = None
    stream: Optional[bool] = False
    # pass-through fields
    temperature: Optional[float] = None
    max_tokens: Optional[int] = Field(None, alias="max_tokens")
    top_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    stop: Optional[Any] = None
    seed: Optional[int] = None
    extra_body: Optional[Dict[str, Any]] = None

@app.post("/v1/chat/completions")
async def mirror_chat(request: Request):
    body = await request.json()
    req = ChatRequest(**body)
    model_id = req.model or ""
    lower_model = model_id.lower()
    target = any(tag in lower_model for tag in [m.lower() for m in TARGET_MODELS]) or any(
        key in lower_model for key in ["gpt-oss-20b", "gpt-oss-120b"]
    )

    schema = _extract_schema_and_type(req.response_format)
    need_transform = target and schema is not None

    # Build payload for upstream
    payload: Dict[str, Any] = body.copy()
    if need_transform:
        payload.pop("response_format", None)
        payload["messages"] = _prepend_schema_instructions(req.messages.copy(), schema)

    async with httpx.AsyncClient(timeout=TIMEOUT_SECS) as client:
        if payload.get("stream"):
            if not need_transform:
                upstream = await client.stream("POST", UPSTREAM_URL, json=payload)

                async def iterator():
                    async for chunk in upstream.aiter_bytes():
                        yield chunk

                headers = {"Content-Type": upstream.headers.get("Content-Type", "text/event-stream")}
                return StreamingResponse(iterator(), headers=headers, status_code=upstream.status_code)

            if need_transform and not ALLOW_STREAM_REPAIR:
                upstream = await client.stream("POST", UPSTREAM_URL, json=payload)

                async def iterator():
                    async for chunk in upstream.aiter_bytes():
                        yield chunk

                headers = {"Content-Type": upstream.headers.get("Content-Type", "text/event-stream")}
                return StreamingResponse(iterator(), headers=headers, status_code=upstream.status_code)

            # Optional: if ALLOW_STREAM_REPAIR=true, disable stream upstream, repair, then re-stream locally.
            if need_transform and ALLOW_STREAM_REPAIR:
                payload_no_stream = dict(payload)
                payload_no_stream["stream"] = False
                r = await client.post(UPSTREAM_URL, json=payload_no_stream)
                r.raise_for_status()
                upstream_json = r.json()
                raw_text = upstream_json["choices"][0]["message"]["content"]
                clean_text = _strip_code_fences(raw_text)
                obj = _try_json_loads(clean_text)
                if obj is None:
                    repaired = await _repair_with_model(clean_text, schema, client, payload_no_stream)
                    if repaired:
                        clean_text = _strip_code_fences(repaired)
                        obj = _try_json_loads(clean_text)
                if obj is not None:
                    err = _validate_against_schema(obj, schema)
                    if err:
                        repaired = await _repair_with_model(clean_text, schema, client, payload_no_stream)
                        if repaired:
                            clean_text = _strip_code_fences(repaired)
                            obj = _try_json_loads(clean_text)
                            if obj is not None:
                                err = _validate_against_schema(obj, schema)
                final_text = json.dumps(obj) if obj is not None else clean_text
                final = _shape_response_like_openai(upstream_json, final_text)
                # Emit as a simple one-shot stream in SSE format
                def sse():
                    chunk = json.dumps({"id": final.get("id", ""), "object":"chat.completion.chunk",
                                        "choices":[{"delta":{"content": final_text}}]})
                    yield f"data: {chunk}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(sse(), media_type="text/event-stream")

        # Non-stream path
        r = await client.post(UPSTREAM_URL, json=payload)
        r.raise_for_status()
        upstream_json = r.json()

        if not need_transform:
            return JSONResponse(content=upstream_json, status_code=r.status_code)

        # Validate and repair
        raw_text = upstream_json["choices"][0]["message"]["content"]
        clean_text = _strip_code_fences(raw_text)
        obj = _try_json_loads(clean_text)

        if obj is None:
            repaired = await _repair_with_model(clean_text, schema, client, payload)
            if repaired:
                clean_text = _strip_code_fences(repaired)
                obj = _try_json_loads(clean_text)

        if obj is not None:
            err = _validate_against_schema(obj, schema)
            if err:
                repaired = await _repair_with_model(clean_text, schema, client, payload)
                if repaired:
                    clean_text = _strip_code_fences(repaired)
                    obj2 = _try_json_loads(clean_text)
                    if obj2 is not None:
                        obj = obj2
                        err = _validate_against_schema(obj, schema)

        final_text = json.dumps(obj, ensure_ascii=False) if obj is not None else clean_text
        final = _shape_response_like_openai(upstream_json, final_text)
        return JSONResponse(content=final, status_code=r.status_code)

@app.get("/healthz")
def health():
    return {"ok": True, "upstream": UPSTREAM_URL}
