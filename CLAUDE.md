# Development Guidelines

## Python

- Python 3.13.12
- `pyproject.toml` and `uv` for dependency management
- Add dependencies with `uv add`
- ALWAYS run Python with `uv run`
- ALWAYS commit `uv.lock`
- NEVER use `uv run pip` — use `uv add`, `uv remove`, `uv sync`
- When working with Python, invoke the relevant `/astral:<skill>` for uv, ty, and ruff to ensure best practices are followed

## Linting

- `ruff` for linting and formatting
- `ty` for type checking
- Ruff config: use `scaffolding/pyproject.toml` as the template
- Before committing, ALWAYS run: `uv run ruff format`, `uv run ruff check`, `uv run ty check`, `uv run uv lock --check`

## Docker

- Each agent has a Dockerfile — use `scaffolding/Dockerfile` as the template

## Coding Style

- Imports at the top of the file
- Prefer short code
- No explanatory comments

## Documentation

- Always explain agent logic in the README
- Prefer mermaid sequence diagrams (see https://mermaid.js.org/syntax/sequenceDiagram.html)

## Testing

- Write tests with pytest
- Run with `uv run pytest`

## Browser Automation

- Use `playwright-cli` (not the MCP server) for browser automation — it's ~4x more token-efficient
- Invoke the `/playwright-cli` skill when automating browser interactions, testing web pages, taking screenshots, or extracting web data
