"""Bare-minimum FastAPI server for the D&D 5e Wizard Builder."""

import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel as PydanticBaseModel

from models import (
    Ability,
    Alignment,
    Background,
    CantripEntry,
    CharacterSheet,
    Skill,
    Species,
    Spell,
    SpellSchool,
    WeaponEntry,
)

app = FastAPI()

sessions: dict[str, list[dict[str, str]]] = {}

HARDCODED_SHEET = CharacterSheet(
    name="Elara Nightwhisper",
    species=Species.ELF,
    background=Background.SAGE,
    alignment=Alignment.NEUTRAL_GOOD,
    strength=8,
    dexterity=14,
    constitution=13,
    intelligence=17,
    wisdom=12,
    charisma=10,
    ac=12,
    speed=30,
    hp_max=7,
    save_profs=[Ability.INT, Ability.WIS],
    skill_profs=[Skill.ARCANA, Skill.HISTORY, Skill.INSIGHT],
    cantrips=[
        CantripEntry(name="Fire Bolt", hit="+5", damage="1d10 fire"),
        CantripEntry(name="Ray of Frost", hit="+5", damage="1d8 cold"),
        CantripEntry(name="Minor Illusion"),
    ],
    spells=[
        Spell(name="Mage Armor", level=1, school=SpellSchool.ABJURATION, description="AC becomes 13 + DEX mod"),
        Spell(
            name="Magic Missile",
            level=1,
            school=SpellSchool.EVOCATION,
            description="3 darts, 1d4+1 force each",
        ),
        Spell(name="Shield", level=1, school=SpellSchool.ABJURATION, description="+5 AC as reaction"),
        Spell(
            name="Detect Magic",
            level=1,
            school=SpellSchool.DIVINATION,
            ritual=True,
            concentration=True,
            description="Sense magic within 30 ft",
        ),
    ],
    spellbook=[
        Spell(name="Mage Armor", level=1, school=SpellSchool.ABJURATION),
        Spell(name="Magic Missile", level=1, school=SpellSchool.EVOCATION),
        Spell(name="Shield", level=1, school=SpellSchool.ABJURATION),
        Spell(name="Detect Magic", level=1, school=SpellSchool.DIVINATION, ritual=True, concentration=True),
        Spell(name="Feather Fall", level=1, school=SpellSchool.TRANSMUTATION),
        Spell(name="Sleep", level=1, school=SpellSchool.ENCHANTMENT, concentration=True),
    ],
    attacks=[
        WeaponEntry(name="Quarterstaff", hit="-1", damage="1d6-1 bludg."),
        WeaponEntry(name="Dagger", hit="+4", damage="1d4+2 pierc."),
    ],
    features=["Spellcasting", "Ritual Adept", "Arcane Recovery"],
    equipment=[
        "Spellbook",
        "Arcane Focus (Quarterstaff)",
        "2 Daggers",
        "Robe",
        "Scholar's Pack",
    ],
    gp=5,
    personality="I use polysyllabic words that convey the impression of great erudition.",
    ideals="Knowledge. The path to power and self-improvement is through knowledge.",
    bonds="My spellbook is my most prized possession — a reminder of everything I've learned.",
    flaws="I speak without really thinking through what I'm saying, invariably insulting others.",
)

HARDCODED_SHEET_DICT = json.loads(
    HARDCODED_SHEET.model_dump_json(by_alias=True, exclude={"spellbook"})
)

HARDCODED_SHEET_DICT["race"] = HARDCODED_SHEET_DICT.pop("species")


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

    is_sheet_request = "character sheet" in req.message.lower()

    async def generate() -> AsyncGenerator[str]:
        yield f"event: session\ndata: {sid}\n\n"

        if is_sheet_request:
            yield "data: Here is your character sheet!\n\n"
            yield f"event: character_sheet\ndata: {json.dumps(HARDCODED_SHEET_DICT)}\n\n"
        else:
            reply = (
                "I'm the Wizard Builder guide. I'll help you create a Level 1 D&D 5e (2024) Wizard. "
                'Try asking for your "character sheet" to see an example!'
            )
            yield f"data: {reply}\n\n"
            sessions[sid].append({"role": "assistant", "content": reply})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/clear")
async def clear(req: ClearRequest) -> dict[str, str]:
    """Clear a chat session."""
    sessions.pop(req.session_id, None)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
