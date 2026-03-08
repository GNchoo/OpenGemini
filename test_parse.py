import json

output = """
YOLO mode is enabled. All tool calls will be automatically approved.
Error during discovery for MCP server 'sqlite': MCP error -32000
{
  "response": "Here is the code you requested: \\n```python\\ndef my_func():\\n    return {'hello': 'world'}\\n```"
}
Server 'filesystem' supports tool updates.
"""

response_text = ""
decoder = json.JSONDecoder()
idx = 0
parsed_objects = []
while idx < len(output):
    idx = output.find('{', idx)
    if idx == -1:
        break
    try:
        obj, end_idx = decoder.raw_decode(output[idx:])
        parsed_objects.append(obj)
        idx += end_idx
    except json.JSONDecodeError as e:
        idx += 1

for data in reversed(parsed_objects):
    if isinstance(data, dict):
        found = data.get("response") or data.get("summary", {}).get("totalResponse")
        if found:
            response_text = str(found).strip()
            break

print("EXTRACTED:", response_text)
