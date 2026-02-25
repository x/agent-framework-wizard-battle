#!/bin/bash

file=$(python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    pass
")

[[ "$file" == *.py ]] && [[ -f "$file" ]] || exit 0

# Walk up to find the nearest pyproject.toml
dir=$(dirname "$(realpath "$file")")
while [[ "$dir" != "/" ]] && [[ ! -f "$dir/pyproject.toml" ]]; do
    dir=$(dirname "$dir")
done

[[ -f "$dir/pyproject.toml" ]] || exit 0

cd "$dir"
uv run ruff format "$file" --quiet
uv run ruff check "$file"
uv run ty check "$file"
