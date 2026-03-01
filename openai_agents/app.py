"""OpenAI Agents SDK-based D&D 5e Wizard Builder agent."""

from __future__ import annotations

import json
import logging
import os
import random
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
import jinja2
from agents import Agent, RunContextWrapper, Runner, TResponseInputItem, function_tool, handoff
from agents.extensions.models.litellm_model import LitellmModel
from agents.stream_events import AgentUpdatedStreamEvent, RawResponsesStreamEvent, RunItemStreamEvent
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from openai.types.responses import ResponseTextDeltaEvent
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ValidationError

from models import CantripEntry, CharacterSheet, Spell, SpellSchool

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("wizard")


# ── RAG ──

DB_PATH = Path(__file__).resolve().parent / "chroma_db"
_chroma: chromadb.ClientAPI | None = None


def _get_chroma() -> chromadb.ClientAPI:
    global _chroma  # noqa: PLW0603
    if _chroma is None:
        _chroma = chromadb.PersistentClient(path=str(DB_PATH))
    return _chroma


# ── Prompt templates ──

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).resolve().parent / "prompts"),
    keep_trailing_newline=False,
)


def _prompt(name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(f"{name}.j2").render(**kwargs)


def _validation_msg(exc: ValidationError) -> str:
    msg = exc.errors()[0]["msg"]
    return msg.removeprefix("Value error, ")


# ── Context ──


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


@dataclass
class WizardContext:
    """Typed context shared across all agents, tools, and hooks in a run.

    Mutations are immediately visible everywhere — no serialize/deserialize.
    """

    sheet: CharacterSheet = field(default_factory=CharacterSheet)
    steps: list[Step] = field(default_factory=lambda: [s.model_copy() for s in _STEPS])
    sheet_dirty: bool = False

    def mark_step_done(self, agent_name: str) -> None:
        """Mark the step belonging to the given agent as complete."""
        for step in self.steps:
            if step.agent_name == agent_name:
                step.is_done = True
                break

    def next_step(self) -> Step | None:
        """Return the next incomplete step, or None if all done."""
        return next((s for s in self.steps if not s.is_done), None)


# ── Tools ──


@function_tool
def roll_ability_score() -> int:
    """Roll one D&D ability score: roll 4d6 and drop the lowest die.

    Returns:
        Sum of the three highest dice from a roll of 4d6 (range 3-18).

    """
    rolls = sorted([random.randint(1, 6) for _ in range(4)], reverse=True)
    total = sum(rolls[:3])
    log.info("roll_ability_score: rolls=%s → %d", rolls, total)
    return total


@function_tool
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


@function_tool
def finalize_name(ctx: RunContextWrapper[WizardContext], name: str) -> dict[str, object]:
    """Finalize the character name and set wizard class baseline.

    Args:
        ctx: Injected by SDK.
        name: The character's name.

    """
    wc = ctx.context
    log.info("finalize_name: name=%r", name)
    try:
        wc.sheet.name = name
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    wc.sheet.save_profs = ["int", "wis"]
    wc.sheet.features = ["Spellcasting", "Ritual Adept", "Arcane Recovery"]
    wc.mark_step_done("name_agent")
    wc.sheet_dirty = True
    return {"status": "ok"}


@function_tool
def finalize_background(
    ctx: RunContextWrapper[WizardContext],
    background: str,
    skill_profs: list[str],
    equipment: list[str],
    gp: int,
) -> dict[str, object]:
    """Finalize background, skills, and starting equipment.

    Args:
        ctx: Injected by SDK.
        background: The background name (e.g., "Sage").
        skill_profs: All 4 skill proficiency names in lowercase.
        equipment: Complete starting equipment list.
        gp: Starting gold pieces.

    """
    wc = ctx.context
    log.info("finalize_background: bg=%r skills=%s", background, skill_profs)
    try:
        wc.sheet.background = background
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    wc.sheet.skill_profs = skill_profs
    wc.sheet.equipment = equipment
    wc.sheet.gp = gp
    wc.mark_step_done("background_agent")
    wc.sheet_dirty = True
    return {"status": "ok"}


@function_tool
def finalize_species(ctx: RunContextWrapper[WizardContext], race: str, speed: int) -> dict[str, object]:
    """Finalize the chosen species/lineage.

    Args:
        ctx: Injected by SDK.
        race: The species/lineage name (e.g., "High Elf").
        speed: Walking speed in feet (usually 30 or 35).

    """
    wc = ctx.context
    log.info("finalize_species: race=%r speed=%d", race, speed)
    try:
        wc.sheet.race = race
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    wc.sheet.speed = speed
    wc.mark_step_done("species_agent")
    wc.sheet_dirty = True
    return {"status": "ok"}


@function_tool
def finalize_ability_scores(
    ctx: RunContextWrapper[WizardContext],
    str_score: int,
    dex_score: int,
    con_score: int,
    int_score: int,
    wis_score: int,
    cha_score: int,
) -> dict[str, object]:
    """Finalize ability scores, compute HP and AC.

    Args:
        ctx: Injected by SDK.
        str_score: Final Strength (post-ASI).
        dex_score: Final Dexterity (post-ASI).
        con_score: Final Constitution (post-ASI).
        int_score: Final Intelligence (post-ASI).
        wis_score: Final Wisdom (post-ASI).
        cha_score: Final Charisma (post-ASI).

    """
    wc = ctx.context
    log.info(
        "finalize_ability_scores: STR=%d DEX=%d CON=%d INT=%d WIS=%d CHA=%d",
        str_score,
        dex_score,
        con_score,
        int_score,
        wis_score,
        cha_score,
    )
    wc.sheet.strength = str_score
    wc.sheet.dexterity = dex_score
    wc.sheet.constitution = con_score
    wc.sheet.intelligence = int_score
    wc.sheet.wisdom = wis_score
    wc.sheet.charisma = cha_score
    wc.sheet.hp_max = 6 + (con_score - 10) // 2
    wc.sheet.ac = 10 + (dex_score - 10) // 2
    wc.mark_step_done("ability_scores_agent")
    wc.sheet_dirty = True
    return {"status": "ok", "hp_max": wc.sheet.hp_max, "ac": wc.sheet.ac}


@function_tool
def finalize_alignment(ctx: RunContextWrapper[WizardContext], alignment: str) -> dict[str, object]:
    """Finalize the chosen alignment.

    Args:
        ctx: Injected by SDK.
        alignment: The full alignment name (e.g., "Neutral Good").

    """
    wc = ctx.context
    log.info("finalize_alignment: alignment=%r", alignment)
    try:
        wc.sheet.alignment = alignment
    except ValidationError as e:
        return {"status": "error", "message": _validation_msg(e)}
    wc.mark_step_done("alignment_agent")
    wc.sheet_dirty = True
    return {"status": "ok"}


@function_tool
def finalize_spells(
    ctx: RunContextWrapper[WizardContext],
    cantrip_names: list[str],
    prepared_spell_names: list[str],
) -> dict[str, object]:
    """Finalize cantrips and prepared spells, validate against INT modifier.

    Args:
        ctx: Injected by SDK.
        cantrip_names: All cantrip names (class + bonus).
        prepared_spell_names: Names of prepared spells, including always-prepared.

    """
    wc = ctx.context
    log.info("finalize_spells: cantrips=%s prepared=%s", cantrip_names, prepared_spell_names)
    int_score = wc.sheet.intelligence or 10
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
    wc.sheet.cantrips = [CantripEntry(name=n, hit=spell_atk) for n in cantrip_names]
    wc.sheet.spells = [Spell(name=n, level=1, school=SpellSchool.EVOCATION) for n in prepared_spell_names]
    wc.mark_step_done("spells_agent")
    wc.sheet_dirty = True
    return {"status": "ok", "spell_attack": spell_atk, "spell_dc": 8 + int_mod + prof}


@function_tool
def finalize_equipment(
    ctx: RunContextWrapper[WizardContext],
    equipment: list[str],
    gp: int,
) -> dict[str, object]:
    """Finalize equipment and compute weapon attacks.

    Args:
        ctx: Injected by SDK.
        equipment: Complete merged equipment list.
        gp: Total gold pieces.

    """
    wc = ctx.context
    log.info("finalize_equipment: equipment=%s gp=%d", equipment, gp)
    str_mod = ((wc.sheet.strength or 10) - 10) // 2
    dex_mod = ((wc.sheet.dexterity or 10) - 10) // 2
    prof = 2

    def fmt(mod: int) -> str:
        return f"+{mod}" if mod >= 0 else str(mod)

    wc.sheet.equipment = equipment
    wc.sheet.gp = gp
    wc.sheet.attacks = [
        {"name": "Quarterstaff", "hit": fmt(str_mod + prof), "damage": f"1d6{fmt(str_mod)} bludg."},
        {"name": "Dagger", "hit": fmt(max(str_mod, dex_mod) + prof), "damage": f"1d4{fmt(dex_mod)} pierc."},
    ]
    wc.mark_step_done("equipment_agent")
    wc.sheet_dirty = True
    return {"status": "ok"}


@function_tool
def finalize_personality(
    ctx: RunContextWrapper[WizardContext],
    personality: str,
    ideals: str,
    bonds: str,
    flaws: str,
) -> dict[str, object]:
    """Finalize personality traits, ideals, bonds, and flaws.

    Args:
        ctx: Injected by SDK.
        personality: Personality trait text.
        ideals: Ideals text.
        bonds: Bonds text.
        flaws: Flaws text.

    """
    wc = ctx.context
    log.info("finalize_personality: %r / %r / %r / %r", personality, ideals, bonds, flaws)
    if any(v.lower() in ("placeholder", "tbd", "n/a", "") for v in [personality, ideals, bonds, flaws]):
        return {
            "status": "error",
            "message": "Personality fields contain placeholder values. Ask the user for their actual "
            "Trait, Ideal, Bond, and Flaw before calling finalize_personality.",
        }
    wc.sheet.personality = personality
    wc.sheet.ideals = ideals
    wc.sheet.bonds = bonds
    wc.sheet.flaws = flaws
    wc.mark_step_done("personality_agent")
    wc.sheet_dirty = True
    return {"status": "ok"}


# ── Agents ──

_SAGE_BACKGROUNDS = frozenset({"Sage"})
_BONUS_CANTRIP_SPECIES = frozenset({"High Elf"})


def _orchestrator_instruction(ctx: RunContextWrapper[WizardContext], _agent: Agent[WizardContext]) -> str:
    wc = ctx.context
    rules = [
        "NEVER answer D&D questions yourself — always hand off to the appropriate step agent.",
        "NEVER skip steps or go backwards.",
    ]

    if not any(s.is_done for s in wc.steps):
        rules.append(
            "This is a NEW session. Greet the user warmly and explain you will guide them "
            "through building a Level 1 D&D 5e Wizard in 8 steps. List the steps briefly. "
            "Then IMMEDIATELY hand off to `name_agent`.",
        )
    elif all(s.is_done for s in wc.steps):
        rules.append("ALL steps are complete! Congratulate the user on finishing their wizard. Do NOT hand off.")
    else:
        nxt = next(s for s in wc.steps if not s.is_done)
        rules.append(f"Hand off to `{nxt.agent_name}` for the next incomplete step.")

    instruction = f"""\
You are the orchestrator for a D&D 5e Wizard character builder.

<progress>
{chr(10).join(str(s) for s in wc.steps)}
</progress>

<rules>
{chr(10).join(f"- {r}" for r in rules)}
</rules>
"""
    log.info("Orchestrator instruction:\n%s", instruction)
    return instruction


def _spells_instruction(ctx: RunContextWrapper[WizardContext], _agent: Agent[WizardContext]) -> str:
    sheet = ctx.context.sheet

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


def build_agents(model_str: str) -> Agent[WizardContext]:
    """Build the full agent graph. Returns the orchestrator."""
    model = LitellmModel(model=model_str, api_key="unused")

    # Step agents — defined first, handoffs wired after orchestrator exists.
    name_agent = Agent[WizardContext](
        name="name_agent",
        instructions=_prompt("name"),
        model=model,
        tools=[finalize_name],
    )
    background_agent = Agent[WizardContext](
        name="background_agent",
        instructions=_prompt("background"),
        model=model,
        tools=[query_rag, finalize_background],
    )
    species_agent = Agent[WizardContext](
        name="species_agent",
        instructions=_prompt("species"),
        model=model,
        tools=[query_rag, finalize_species],
    )
    ability_scores_agent = Agent[WizardContext](
        name="ability_scores_agent",
        instructions=_prompt("ability_scores"),
        model=model,
        tools=[roll_ability_score, finalize_ability_scores, query_rag],
    )
    alignment_agent = Agent[WizardContext](
        name="alignment_agent",
        instructions=_prompt("alignment"),
        model=model,
        tools=[finalize_alignment],
    )
    spells_agent = Agent[WizardContext](
        name="spells_agent",
        instructions=_spells_instruction,
        model=model,
        tools=[query_rag, finalize_spells],
    )
    equipment_agent = Agent[WizardContext](
        name="equipment_agent",
        instructions=_prompt("equipment"),
        model=model,
        tools=[finalize_equipment, query_rag],
    )
    personality_agent = Agent[WizardContext](
        name="personality_agent",
        instructions=_prompt("personality"),
        model=model,
        tools=[finalize_personality],
    )

    step_agents = [
        name_agent,
        background_agent,
        species_agent,
        ability_scores_agent,
        alignment_agent,
        spells_agent,
        equipment_agent,
        personality_agent,
    ]

    orchestrator = Agent[WizardContext](
        name="wizard_orchestrator",
        instructions=_orchestrator_instruction,
        model=model,
        handoffs=[handoff(agent=a) for a in step_agents],
    )

    for a in step_agents:
        a.handoffs = [handoff(agent=orchestrator)]

    return orchestrator


MODEL_STR = os.environ["MODEL"]
orchestrator = build_agents(MODEL_STR)


# ── FastAPI ──

app = FastAPI()

sessions: dict[str, tuple[WizardContext, list[TResponseInputItem], Agent[WizardContext]]] = {}


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

    if sid in sessions:
        wctx, prev_input, last_agent = sessions[sid]
    else:
        wctx = WizardContext()
        prev_input: list[TResponseInputItem] = []
        last_agent: Agent[WizardContext] = orchestrator

    run_input: list[TResponseInputItem] = [*prev_input, {"role": "user", "content": req.message}]

    async def generate() -> AsyncGenerator[str]:
        yield f"event: session\ndata: {sid}\n\n"

        wctx.sheet_dirty = False
        log.info("Steps: %s", [(s.agent_name, s.is_done) for s in wctx.steps])

        try:
            log.info("Handoff → %s", last_agent.name)
            result = Runner.run_streamed(
                starting_agent=last_agent,
                input=run_input,
                context=wctx,
                max_turns=25,
            )

            async for event in result.stream_events():
                if isinstance(event, RawResponsesStreamEvent) and isinstance(event.data, ResponseTextDeltaEvent):
                    delta = event.data.delta or ""
                    if delta:
                        yield f"data: {json.dumps(delta)}\n\n"

                elif isinstance(event, RunItemStreamEvent):
                    if event.item.type == "tool_call_output_item" and wctx.sheet_dirty:
                        sheet_json = wctx.sheet.model_dump_json(by_alias=True)
                        yield f"event: character_sheet\ndata: {sheet_json}\n\n"
                        wctx.sheet_dirty = False

                elif isinstance(event, AgentUpdatedStreamEvent):
                    log.info("Handoff → %s", event.new_agent.name)

            input_list = result.to_input_list()
            log.info("to_input_list: %d items, last_agent=%s", len(input_list), result.last_agent.name)
            sessions[sid] = (wctx, input_list, result.last_agent)

        except Exception:  # noqa: BLE001
            log.exception("Error in chat stream")
            yield "data: An error occurred. Please try again.\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/clear")
async def clear(req: ClearRequest) -> dict[str, str]:
    """Clear a chat session."""
    sessions.pop(req.session_id, None)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
