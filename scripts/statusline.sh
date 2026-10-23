#!/bin/bash
input=$(cat)

python3 -c '
import json, sys

try:
    data = json.loads(sys.argv[1])
except Exception:
    data = {}

cw = data.get("context_window", {})
size = cw.get("context_window_size") or 1000000
used = cw.get("used_tokens")
if used is None:
    if "total_input_tokens" in cw:
        used = cw["total_input_tokens"] + cw.get("total_output_tokens", 0)
    elif "used_percentage" in cw and cw["used_percentage"] is not None:
        used = int(round(size * (cw["used_percentage"] / 100.0)))
    else:
        used = 0

pct = (used / size * 100) if size else 0
if pct >= 80:
    color = "\033[31m"
elif pct >= 60:
    color = "\033[33m"
else:
    color = "\033[32m"
reset = "\033[0m"

model = data.get("model", {}).get("display_name", "Gemini")
print(f"{model} | Context: {color}{used:,} / {size:,}{reset} tokens")
' "$input"
