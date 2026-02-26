.PHONY: up index eval

up:
	uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload

index:
	uv run python indexing_pipeline.py

eval:
	uv run pytest eval.py -s
