import requests
import json

BASE = "http://localhost:1235/v1"  # change to your LAN IP if testing from another device
URL = f"{BASE}/chat/completions"

messages = [
    {"role": "system", "content": "You are a helpful math tutor. Be concise."},
    {"role": "user", "content": "Solve 8x + 7 = -23 step by step."},
]

schema = {
    "name": "math_response",
    "schema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "explanation": {"type": "string"},
                        "output": {"type": "string"}
                    },
                    "required": ["explanation", "output"],
                    "additionalProperties": False
                }
            },
            "final_answer": {"type": "string"}
        },
        "required": ["steps", "final_answer"],
        "additionalProperties": False
    }
}

payload = {
    "model": "openai/gpt-oss-20b",
    "messages": messages,
    "temperature": 0.2,
    "stream": False,
    "response_format": {
        "type": "json_schema",
        "json_schema": schema
    }
}

r = requests.post(URL, json=payload, timeout=120)
r.raise_for_status()
data = r.json()
content = data["choices"][0]["message"]["content"]
print(json.dumps(json.loads(content), indent=2, ensure_ascii=False))
