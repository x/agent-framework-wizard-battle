"""Bare-minimum FastAPI server for the D&D 5e Wizard Builder."""

import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import litellm
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel as PydanticBaseModel

load_dotenv()

MODEL = os.environ["MODEL"]
SYSTEM_PROMPT = "You are a helpful guide for building a Level 1 D&D 5e (2024) Wizard."

app = FastAPI()

sessions: dict[str, list[dict[str, str]]] = {}


# ── Request / Response ──


class ChatRequest(PydanticBaseModel):
    """Incoming chat message from the frontend."""

    message: str
    session_id: str | None = None


class ClearRequest(PydanticBaseModel):
    """Clear a chat session."""

    session_id: str


# ── Routes ──


@app.get("/")
async def index() -> FileResponse:
    """Serve the frontend."""
    return FileResponse(Path(__file__).parent / "index.html")


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Handle a chat message. Returns SSE stream."""
    sid = req.session_id or str(uuid.uuid4())
    if sid not in sessions:
        sessions[sid] = []
    sessions[sid].append({"role": "user", "content": req.message})

    async def generate() -> AsyncGenerator[str]:
        yield f"event: session\ndata: {sid}\n\n"

        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *sessions[sid]]
        response = await litellm.acompletion(model=MODEL, messages=messages, stream=True)

        reply_parts: list[str] = []
        async for chunk in response:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                reply_parts.append(delta)
                yield f"data: {delta}\n\n"

        sessions[sid].append({"role": "assistant", "content": "".join(reply_parts)})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/clear")
async def clear(req: ClearRequest) -> dict[str, str]:
    """Clear a chat session."""
    sessions.pop(req.session_id, None)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
