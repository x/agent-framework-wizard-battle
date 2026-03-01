"""Google ADK-based D&D 5e Wizard Builder agent."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import random
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import chromadb
import jinja2
import litellm
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai.types import Content, Part
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ValidationError

from models import CantripEntry, CharacterSheet, Spell, SpellSchool

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

litellm.num_retries = 5
litellm.request_timeout = 120

# ── RAG ──

DB_PATH = Path(__file__).resolve().parent / "chroma_db"
_chroma: chromadb.ClientAPI | None = None


def _get_chroma() -> chromadb.ClientAPI:
    global _chroma  # noqa: PLW0603
    if _chroma is None:
        _chroma = chromadb.PersistentClient(path=str(DB_PATH))
    return _chroma


# ── Model ──

MODEL = LiteLlm(model=os.environ["MODEL"], temperature=0.2)

# ── Prompt templates ──

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).resolve().parent / "prompts"),
    keep_trailing_newline=False,
)


def _prompt(name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(f"{name}.j2").render(**kwargs)


log = logging.getLogger("wizard")


def _validation_msg(exc: ValidationError) -> str:
    msg = exc.errors()[0]["msg"]
    return msg.removeprefix("Value error, ")


class StateManager:
    """Load, mutate, and persist session state for a single tool call."""

    def __init__(self, tc: ToolContext) -> None:  # noqa: D107
        self._tc = tc
        self.sheet = CharacterSheet.model_validate_json(tc.state.get("sheet", "{}"))
        self.steps: list[Step] = tc.state.get("steps", [])

    def save(self) -> None:
        """Persist sheet + steps back to session state."""
        self._tc.state["sheet"] = self.sheet.model_dump_json(by_alias=True)
        self._tc.state["steps"] = self.steps

    def mark_step_done(self) -> None:
        """Mark the current agent's step as complete."""
        for step in self.steps:
            if step.agent_name == self._tc.agent_name:
                step.is_done = True
                break

    @property
    def agent(self) -> str:
        """Current agent name (for logging)."""
        return self._tc.agent_name or "?"


# ── Tools ──


def roll_ability_score() -> int:
    """Roll one D&D ability score: roll 4d6 and drop the lowest die.

    Returns:
        Sum of the three highest dice from a roll of 4d6 (range 3-18).

    """
    rolls = sorted([random.randint(1, 6) for _ in range(4)], reverse=True)
    total = sum(rolls[:3])
    log.info("roll_ability_score: rolls=%s → %d", rolls, total)
    return total


def query_rag(collection: str, query: str) -> str:
    """Query a PHB 2024 RAG collection for relevant rules and descriptions.

    Args:
        collection: One of: classes, backgrounds, species, feats, equipment, spells, rules.
        query: The search query.

    Returns:
        Relevant text chunks from the Player's Handbook.

    """
    log.info("query_rag: collection=%r query=%r", collection, query)
    try:
        col = _get_chroma().get_collection(collection)
    except Exception:  # noqa: BLE001
        log.warning("query_rag: collection %r not found", collection)
        return f"Collection '{collection}' not available. Use your D&D 5e 2024 knowledge."
    results = col.query(query_texts=[query], n_results=3)
    docs = (results.get("documents") or [[]])[0]
    titles = [m.get("title", "") for m in (results.get("metadatas") or [[]])[0]]
    log.info("query_rag: %d results, titles=%s", len(docs), titles)
    chunks = [f"### {t}\n{d}" for t, d in zip(titles, docs, strict=True)]
    return "\n\n---\n\n".join(chunks) if chunks else "No results found."


def finalize_name(name: str, tool_context: ToolContext) -> dict[str, object]:
    """Finalize the character name and set wizard class baseline.

    Args:
        name: The character's name.
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info("[%s] finalize_name: name=%r", sm.agent, name)
    try:
        sm.sheet.name = name
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    sm.sheet.save_profs = ["int", "wis"]
    sm.sheet.features = ["Spellcasting", "Ritual Adept", "Arcane Recovery"]
    sm.mark_step_done()
    sm.save()
    return {"status": "ok"}


def finalize_background(
    background: str, skill_profs: list[str], equipment: list[str], gp: int, tool_context: ToolContext
) -> dict[str, object]:
    """Finalize background, skills, and starting equipment.

    Args:
        background: The background name (e.g., "Sage").
        skill_profs: All 4 skill proficiency names in lowercase.
        equipment: Complete starting equipment list.
        gp: Starting gold pieces.
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info("[%s] finalize_background: bg=%r skills=%s", sm.agent, background, skill_profs)
    try:
        sm.sheet.background = background
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    sm.sheet.skill_profs = skill_profs
    sm.sheet.equipment = equipment
    sm.sheet.gp = gp
    sm.mark_step_done()
    sm.save()
    return {"status": "ok"}


def finalize_species(race: str, speed: int, tool_context: ToolContext) -> dict[str, object]:
    """Finalize the chosen species/lineage.

    Args:
        race: The species/lineage name (e.g., "High Elf").
        speed: Walking speed in feet (usually 30 or 35).
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info("[%s] finalize_species: race=%r speed=%d", sm.agent, race, speed)
    try:
        sm.sheet.race = race
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    sm.sheet.speed = speed
    sm.mark_step_done()
    sm.save()
    return {"status": "ok"}


def finalize_ability_scores(
    str_score: int,
    dex_score: int,
    con_score: int,
    int_score: int,
    wis_score: int,
    cha_score: int,
    tool_context: ToolContext,
) -> dict[str, object]:
    """Finalize ability scores, compute HP and AC.

    Args:
        str_score: Final Strength (post-ASI).
        dex_score: Final Dexterity (post-ASI).
        con_score: Final Constitution (post-ASI).
        int_score: Final Intelligence (post-ASI).
        wis_score: Final Wisdom (post-ASI).
        cha_score: Final Charisma (post-ASI).
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info(
        "[%s] finalize_ability_scores: STR=%d DEX=%d CON=%d INT=%d WIS=%d CHA=%d",
        sm.agent,
        str_score,
        dex_score,
        con_score,
        int_score,
        wis_score,
        cha_score,
    )
    sm.sheet.strength = str_score
    sm.sheet.dexterity = dex_score
    sm.sheet.constitution = con_score
    sm.sheet.intelligence = int_score
    sm.sheet.wisdom = wis_score
    sm.sheet.charisma = cha_score
    sm.sheet.hp_max = 6 + (con_score - 10) // 2
    sm.sheet.ac = 10 + (dex_score - 10) // 2
    sm.mark_step_done()
    sm.save()
    return {"status": "ok", "hp_max": sm.sheet.hp_max, "ac": sm.sheet.ac}


def finalize_alignment(alignment: str, tool_context: ToolContext) -> dict[str, object]:
    """Finalize the chosen alignment.

    Args:
        alignment: The full alignment name (e.g., "Neutral Good").
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info("[%s] finalize_alignment: alignment=%r", sm.agent, alignment)
    try:
        sm.sheet.alignment = alignment
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    sm.mark_step_done()
    sm.save()
    return {"status": "ok"}


def finalize_spells(
    cantrip_names: list[str], prepared_spell_names: list[str], tool_context: ToolContext
) -> dict[str, object]:
    """Finalize cantrips and prepared spells, validate against INT modifier.

    Args:
        cantrip_names: All cantrip names (class + bonus).
        prepared_spell_names: Names of prepared spells, including always-prepared.
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info("[%s] finalize_spells: cantrips=%s prepared=%s", sm.agent, cantrip_names, prepared_spell_names)
    int_score = sm.sheet.intelligence or 10
    int_mod = (int_score - 10) // 2
    max_prepared = int_mod + 1

    non_auto = [s for s in prepared_spell_names if s != "Comprehend Languages"]
    if len(non_auto) < max_prepared:
        return {
            "status": "error",
            "message": f"Not enough prepared spells. INT {int_score} (mod {int_mod:+d}) → "
            f"can prepare {max_prepared}. Ask the user which spells to prepare.",
        }
    if len(non_auto) > max_prepared:
        return {
            "status": "error",
            "message": f"Too many prepared spells. INT {int_score} (mod {int_mod:+d}) → "
            f"can only prepare {max_prepared}, plus always-prepared. Ask the user which {max_prepared} to keep.",
        }

    prof = 2
    spell_atk = f"+{int_mod + prof}"
    sm.sheet.cantrips = [CantripEntry(name=n, hit=spell_atk) for n in cantrip_names]
    sm.sheet.spells = [Spell(name=n, level=1, school=SpellSchool.EVOCATION) for n in prepared_spell_names]
    sm.mark_step_done()
    sm.save()
    return {"status": "ok", "spell_attack": spell_atk, "spell_dc": 8 + int_mod + prof}


def finalize_equipment(equipment: list[str], gp: int, tool_context: ToolContext) -> dict[str, object]:
    """Finalize equipment and compute weapon attacks.

    Args:
        equipment: Complete merged equipment list.
        gp: Total gold pieces.
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info("[%s] finalize_equipment: equipment=%s gp=%d", sm.agent, equipment, gp)
    str_mod = ((sm.sheet.strength or 10) - 10) // 2
    dex_mod = ((sm.sheet.dexterity or 10) - 10) // 2
    prof = 2

    def fmt(mod: int) -> str:
        return f"+{mod}" if mod >= 0 else str(mod)

    sm.sheet.equipment = equipment
    sm.sheet.gp = gp
    sm.sheet.attacks = [
        {"name": "Quarterstaff", "hit": fmt(str_mod + prof), "damage": f"1d6{fmt(str_mod)} bludg."},
        {"name": "Dagger", "hit": fmt(max(str_mod, dex_mod) + prof), "damage": f"1d4{fmt(dex_mod)} pierc."},
    ]
    sm.mark_step_done()
    sm.save()
    return {"status": "ok"}


def finalize_personality(
    personality: str, ideals: str, bonds: str, flaws: str, tool_context: ToolContext
) -> dict[str, object]:
    """Finalize personality traits, ideals, bonds, and flaws.

    Args:
        personality: Personality trait text.
        ideals: Ideals text.
        bonds: Bonds text.
        flaws: Flaws text.
        tool_context: Injected by ADK.

    """
    sm = StateManager(tool_context)
    log.info("[%s] finalize_personality: %r / %r / %r / %r", sm.agent, personality, ideals, bonds, flaws)
    if any(v.lower() in ("placeholder", "tbd", "n/a", "") for v in [personality, ideals, bonds, flaws]):
        return {
            "status": "error",
            "message": "Personality fields contain placeholder values. Ask the user for their actual "
            "Trait, Ideal, Bond, and Flaw before calling finalize_personality.",
        }
    sm.sheet.personality = personality
    sm.sheet.ideals = ideals
    sm.sheet.bonds = bonds
    sm.sheet.flaws = flaws
    sm.mark_step_done()
    sm.save()
    return {"status": "ok"}


# ── Step Agents ──

name_agent = LlmAgent(
    name="name_agent",
    description="Step 1: Ask the user for their character name and finalize it.",
    model=MODEL,
    instruction=_prompt("name"),
    tools=[finalize_name],
)

background_agent = LlmAgent(
    name="background_agent",
    description="Step 2: Help the user choose a background (e.g. Sage, Noble).",
    model=MODEL,
    instruction=_prompt("background"),
    tools=[query_rag, finalize_background],
)

species_agent = LlmAgent(
    name="species_agent",
    description="Step 3: Help the user choose a species/lineage (e.g. Elf, Human).",
    model=MODEL,
    instruction=_prompt("species"),
    tools=[query_rag, finalize_species],
)

ability_scores_agent = LlmAgent(
    name="ability_scores_agent",
    description="Step 4: Determine ability scores via standard array or rolling.",
    model=MODEL,
    instruction=_prompt("ability_scores"),
    tools=[roll_ability_score, finalize_ability_scores, query_rag],
)

alignment_agent = LlmAgent(
    name="alignment_agent",
    description="Step 5: Help the user choose an alignment.",
    model=MODEL,
    instruction=_prompt("alignment"),
    tools=[finalize_alignment],
)

_SAGE_BACKGROUNDS = frozenset({"Sage"})
_BONUS_CANTRIP_SPECIES = frozenset({"High Elf"})


def _spells_instruction(ctx: ReadonlyContext) -> str:
    sheet = CharacterSheet.model_validate_json(ctx.state.get("sheet", "{}"))
    has_magic_initiate = sheet.background in _SAGE_BACKGROUNDS
    has_species_cantrip = sheet.race in _BONUS_CANTRIP_SPECIES

    bonus_spellbook = 1 if has_magic_initiate else 0
    bonus_cantrips_feat = 2 if has_magic_initiate else 0
    bonus_cantrips_species = 1 if has_species_cantrip else 0
    total_spellbook = 6 + bonus_spellbook
    total_cantrips = 3 + bonus_cantrips_feat + bonus_cantrips_species

    int_mod = ((sheet.intelligence or 10) - 10) // 2
    prepared_count = max(int_mod + 1, 1)

    return _prompt(
        "spells",
        total_spellbook=total_spellbook,
        total_cantrips=total_cantrips,
        bonus_spellbook=bonus_spellbook,
        bonus_cantrips_feat=bonus_cantrips_feat,
        bonus_cantrips_species=bonus_cantrips_species,
        prepared_count=prepared_count,
        has_magic_initiate=has_magic_initiate,
        background=sheet.background or "Unknown",
        species=sheet.race or "Unknown",
    )


spells_agent = LlmAgent(
    name="spells_agent",
    description="Step 6: Choose cantrips and prepared spells.",
    model=MODEL,
    instruction=_spells_instruction,
    tools=[query_rag, finalize_spells],
)

equipment_agent = LlmAgent(
    name="equipment_agent",
    description="Step 7: Choose starting equipment.",
    model=MODEL,
    instruction=_prompt("equipment"),
    tools=[finalize_equipment, query_rag],
)

personality_agent = LlmAgent(
    name="personality_agent",
    description="Step 8: Define personality trait, ideals, bonds, and flaws.",
    model=MODEL,
    instruction=_prompt("personality"),
    tools=[finalize_personality],
)

# ── Orchestrator ──


class Step(PydanticBaseModel):
    """A single step in the character creation flow."""

    name: str
    agent_name: str
    is_done: bool = False

    def __str__(self) -> str:  # noqa: D105
        return f"- [{'x' if self.is_done else ' '}] {self.name} → `{self.agent_name}`"


_STEPS = [
    Step(name="Name", agent_name="name_agent"),
    Step(name="Background", agent_name="background_agent"),
    Step(name="Species", agent_name="species_agent"),
    Step(name="Ability Scores", agent_name="ability_scores_agent"),
    Step(name="Alignment", agent_name="alignment_agent"),
    Step(name="Spells", agent_name="spells_agent"),
    Step(name="Equipment", agent_name="equipment_agent"),
    Step(name="Personality", agent_name="personality_agent"),
]


def _initialize_state(callback_context: CallbackContext) -> None:
    if "steps" not in callback_context.state:
        callback_context.state["steps"] = [s.model_copy() for s in _STEPS]
        callback_context.state["sheet"] = CharacterSheet().model_dump_json(by_alias=True)


def _orchestrator_instruction(ctx: ReadonlyContext) -> str:
    steps: list[Step] = ctx.state.get("steps", [])

    rules = [
        "NEVER answer D&D questions yourself — always transfer to the appropriate step agent.",
        "NEVER skip steps or go backwards.",
    ]

    if not any(s.is_done for s in steps):
        rules.append(
            "This is a NEW session. Greet the user warmly and explain you will guide them "
            "through building a Level 1 D&D 5e Wizard in 8 steps. List the steps briefly. "
            "Then IMMEDIATELY transfer to `name_agent`.",
        )
    elif all(s.is_done for s in steps):
        rules.append("ALL steps are complete! Congratulate the user on finishing their wizard. Do NOT transfer.")
    else:
        next_step = next(s for s in steps if not s.is_done)
        rules.append(f"Transfer to `{next_step.agent_name}` for the next incomplete step.")

    return f"""\
You are the orchestrator for a D&D 5e Wizard character builder.

<progress>
{chr(10).join(str(s) for s in steps)}
</progress>

<rules>
{chr(10).join(f"- {r}" for r in rules)}
</rules>
"""


orchestrator = LlmAgent(
    name="wizard_orchestrator",
    description="Routes to the correct step agent based on progress.",
    model=MODEL,
    instruction=_orchestrator_instruction,
    sub_agents=[
        name_agent,
        background_agent,
        species_agent,
        ability_scores_agent,
        alignment_agent,
        spells_agent,
        equipment_agent,
        personality_agent,
    ],
    before_agent_callback=_initialize_state,
)

session_service = InMemorySessionService()
runner = Runner(agent=orchestrator, app_name="wizard_builder", session_service=session_service)

# ── FastAPI ──

app = FastAPI()


class ChatRequest(PydanticBaseModel):
    """Incoming chat message from the frontend."""

    message: str
    session_id: str | None = None


class ClearRequest(PydanticBaseModel):
    """Clear a chat session."""

    session_id: str


@app.get("/")
async def index() -> FileResponse:
    """Serve the frontend."""
    return FileResponse(Path(__file__).parent / "index.html")


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Handle a chat message. Returns an SSE stream."""
    sid = req.session_id or str(uuid.uuid4())

    with contextlib.suppress(Exception):
        await session_service.create_session(
            app_name="wizard_builder",
            user_id=sid,
            session_id=sid,
        )

    content = Content(role="user", parts=[Part.from_text(text=req.message)])

    async def generate() -> AsyncGenerator[str]:
        yield f"data: {json.dumps({'sessionId': sid})}\n\n"
        try:
            async for event in runner.run_async(user_id=sid, session_id=sid, new_message=content):
                yield f"data: {event.model_dump_json(exclude_none=True, by_alias=True)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/clear")
async def clear(req: ClearRequest) -> dict[str, str]:
    """Clear a chat session."""
    with contextlib.suppress(Exception):
        await session_service.delete_session(
            app_name="wizard_builder",
            user_id=req.session_id,
            session_id=req.session_id,
        )
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
