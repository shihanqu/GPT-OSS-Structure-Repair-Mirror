# Health
Invoke-RestMethod http://localhost:1235/healthz

# Plain pass-through
$body = @{
  model = "openai/gpt-oss-20b"
  messages = @(@{role="user"; content="Say ok"})
}
Invoke-RestMethod -Method Post -Uri "http://localhost:1235/v1/chat/completions" `
  -ContentType "application/json" -Body ($body | ConvertTo-Json -Depth 10)

# Structured test
$schema = @{
  "$schema" = "http://json-schema.org/draft-07/schema#"
  title = "Ping"
  type = "object"
  properties = @{ msg = @{ type="string" } }
  required = @("msg")
}
$body = @{
  model = "openai/gpt-oss-20b"
  messages = @(@{role="user"; content="Return any text you want."})
  response_format = @{
    type = "json_schema"
    json_schema = @{ name = "Ping"; schema = $schema }
  }
  stream = $false
}
$r = Invoke-RestMethod -Method Post -Uri "http://localhost:1235/v1/chat/completions" `
  -ContentType "application/json" -Body ($body | ConvertTo-Json -Depth 20)
$r.choices[0].message.content
