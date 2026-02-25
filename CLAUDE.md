# Development Guidelines

## Python

- Python 3.13.12
- `pyproject.toml` and `uv` for dependency management (see https://docs.astral.sh/uv/llms.txt)
- Add dependencies with `uv add`
- ALWAYS run Python with `uv run`
- ALWAYS commit `uv.lock`
- NEVER use `uv run pip` — use `uv add`, `uv remove`, `uv sync`

## Linting

- `ruff` for linting and formatting (see https://docs.astral.sh/ruff/llms.txt)
- `ty` for type checking (see https://docs.astral.sh/ty/llms.txt)
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
