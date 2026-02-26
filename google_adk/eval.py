"""End-to-end evaluation for the D&D 5e Wizard Builder.

An LLM "player" drives the conversation to build a hardcoded character.
A judge LLM scores the result.

Usage::

    uv run python eval.py
    uv run pytest eval.py -s
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv
from litellm import completion
from starlette.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from models import CharacterSheet  # noqa: E402

load_dotenv(_HERE / ".env")

PLAYER_MODEL = os.getenv("EVAL_PLAYER_MODEL", os.getenv("MODEL", "vertex_ai/gemini-2.0-flash"))
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", os.getenv("MODEL", "vertex_ai/gemini-2.0-flash"))
MAX_TURNS = 40

B, G, R, Y, C, D, X = "\033[1m", "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"

# ── App client ──────────────────────────────────────────────────────────────

from app import app  # noqa: E402

client = TestClient(app)

# ── Target character ────────────────────────────────────────────────────────

TARGET = {
    "name": "Aldric Dawnwhisper",
    "background": "Sage",
    "race": "High Elf",
    "ability_scores": "Standard Array: STR=8, DEX=13, CON=14+1=15, INT=15+2=17, WIS=12, CHA=10",
    "alignment": "Neutral Good",
    "cantrips": "Fire Bolt, Mage Hand, Prestidigitation (class); Minor Illusion, Light (Magic Initiate); Message (High Elf bonus)",
    "spellbook": "Mage Armor, Magic Missile, Shield, Detect Magic, Identify, Thunderwave, Comprehend Languages (Magic Initiate)",
    "prepared": "Mage Armor, Magic Missile, Shield, Detect Magic (plus Comprehend Languages always prepared)",
    "equipment": "Option A (gear package)",
    "personality": "Trait: I am obsessed with ancient texts and forbidden lore.",
    "ideals": "Knowledge is worth any cost.",
    "bonds": "My spellbook is my most prized possession — I guard it with my life.",
    "flaws": "I look down on anyone less educated than me.",
    "wizard_skills": "Investigation, Religion",
}

EXPECTED = CharacterSheet.model_validate(
    {
        "name": "Aldric Dawnwhisper",
        "race": "High Elf",
        "background": "Sage",
        "alignment": "Neutral Good",
        "str": 8,
        "dex": 13,
        "con": 15,
        "int": 17,
        "wis": 12,
        "cha": 10,
        "hp_max": 8,
        "ac": 11,
        "speed": 30,
        "save_profs": ["int", "wis"],
    }
)

_PLAYER_SYSTEM = f"""\
You are a player creating a D&D 5e Wizard character. Build EXACTLY this character:

{json.dumps(TARGET, indent=2)}

Rules:
- Give clear, direct answers. No waffling.
- When asked for your name, say: "My character's name is {TARGET["name"]}."
- If asked to confirm, say "Yes" and move on.
- Answer only what's being asked — don't volunteer future steps.
- Keep messages short (1-3 sentences).
- NEVER ask the assistant what to do.
- If the conversation is stuck in a loop (the assistant keeps asking the same thing or \
refusing your valid input after 3+ attempts), call the raise_failure tool to abort."""

_RAISE_FAILURE_TOOL = {
    "type": "function",
    "function": {
        "name": "raise_failure",
        "description": (
            "Call this when the conversation is irrecoverably stuck — "
            "e.g. the assistant keeps asking the same question, refuses valid input "
            "repeatedly, or is going in circles. Provide a reason explaining what went wrong."
        ),
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "Why the conversation is stuck."}},
            "required": ["reason"],
        },
    },
}


class EvalFailure(Exception):
    """Raised when the player LLM decides the conversation is irrecoverably stuck."""


# ── SSE helper ──────────────────────────────────────────────────────────────


def chat(sid: str | None, message: str) -> tuple[str, CharacterSheet | None, str]:
    """POST /chat via TestClient, collect full SSE stream -> (text, sheet, session_id)."""
    text_parts: list[str] = []
    sheet: CharacterSheet | None = None
    new_sid = sid or ""

    with client.stream("POST", "/chat", json={"message": message, "session_id": sid}) as r:
        buf = ""
        for chunk in r.iter_bytes():
            buf += chunk.decode()
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                data = ""
                for line in raw.split("\n"):
                    if line.startswith("data: "):
                        data += line[6:]
                if not data:
                    continue
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if ev.get("sessionId"):
                    new_sid = ev["sessionId"]
                    continue
                if ev.get("error"):
                    text_parts.append(f"[ERROR: {ev['error']}]\n")
                    continue

                sd = (ev.get("actions") or {}).get("stateDelta") or {}
                if "sheet" in sd:
                    raw_sheet = sd["sheet"]
                    try:
                        if isinstance(raw_sheet, str):
                            sheet = CharacterSheet.model_validate_json(raw_sheet)
                        else:
                            sheet = CharacterSheet.model_validate(raw_sheet)
                    except Exception:  # noqa: BLE001
                        pass

                if ev.get("partial"):
                    continue

                for part in (ev.get("content") or {}).get("parts") or []:
                    fc = part.get("functionCall")
                    if fc:
                        args_str = json.dumps(fc.get("args", {}), ensure_ascii=False)
                        if len(args_str) > 200:
                            args_str = args_str[:197] + "..."
                        text_parts.append(f"[tool: {fc['name']}({args_str})]\n")
                    elif part.get("text"):
                        text_parts.append(part["text"])

    return "".join(text_parts), sheet, new_sid


# ── Player LLM ──────────────────────────────────────────────────────────────


def _next_player_message(sheet: CharacterSheet, last_assistant: str) -> str:
    lower = last_assistant.lower()

    if not sheet.name:
        return f"My character's name is {TARGET['name']}."

    if not sheet.background:
        if "(a)" in lower and "(b)" in lower:
            return "Option A please."
        if "confirm" in lower:
            return "Yes, confirmed. Option A for equipment. Please finalize the background."
        return (
            f"I choose the {TARGET['background']} background. "
            f"For my Wizard class skills I pick {TARGET['wizard_skills']}. "
            "I'll take equipment Option A."
        )

    if not sheet.race:
        if "confirm" in lower:
            return "Yes, confirmed."
        return f"{TARGET['race']}."

    if sheet.strength is None:
        if "confirm" in lower or "look" in lower or "sound" in lower:
            return "Yes, those scores are correct. Please finalize."
        return (
            "I'll use the Standard Array. Assign as: STR=8, DEX=13, CON=14, INT=15, WIS=12, CHA=10. "
            "Then apply Background ASI: +2 INT (15->17), +1 CON (14->15). "
            "Final: STR=8, DEX=13, CON=15, INT=17, WIS=12, CHA=10."
        )

    if not sheet.alignment:
        return f"{TARGET['alignment']}."

    if not sheet.cantrips:
        if "confirm" in lower or "finalize" in lower:
            return "Yes, please finalize my spells as listed."
        return (
            f"My cantrips: {TARGET['cantrips']}. "
            f"Spellbook: {TARGET['spellbook']}. "
            f"Prepared: {TARGET['prepared']}. Please finalize my spells."
        )

    if not sheet.attacks:
        if "(a)" in lower and "(b)" in lower:
            return "Option A please."
        if "confirm" in lower:
            return "Yes, confirmed. Finalize equipment."
        return f"{TARGET['equipment']}."

    if not sheet.personality:
        if "confirm" in lower or "happy" in lower or "look" in lower:
            return "Yes, finalize my personality please."
        return (
            f"Trait: {TARGET['personality']} Ideal: {TARGET['ideals']} Bond: {TARGET['bonds']} Flaw: {TARGET['flaws']}"
        )

    return "Yes, that looks great! Thank you."


def player_reply(history: list[dict], sheet: CharacterSheet) -> str:
    recent = history[-12:] if len(history) > 12 else history
    msgs = [{"role": "system", "content": _PLAYER_SYSTEM}, *recent]
    try:
        resp = completion(model=PLAYER_MODEL, messages=msgs, max_tokens=300, tools=[_RAISE_FAILURE_TOOL])
        if resp.choices:
            choice = resp.choices[0]
            msg = choice.message
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.function.name == "raise_failure":
                        args = json.loads(tc.function.arguments)
                        raise EvalFailure(args.get("reason", "Player LLM aborted (no reason given)"))
            text = (msg.content or "").strip()
            if text:
                return text
    except EvalFailure:
        raise
    except Exception:  # noqa: BLE001
        pass
    last_assistant = history[-1]["content"] if history and history[-1]["role"] == "assistant" else ""
    return _next_player_message(sheet, last_assistant)


# ── Sheet checker ────────────────────────────────────────────────────────────


def check_sheet(sheet: CharacterSheet) -> list[str]:
    """Compare sheet against EXPECTED. Returns list of error strings."""
    errors: list[str] = []
    actual = sheet.model_dump(by_alias=True)
    expected = EXPECTED.model_dump(by_alias=True)

    for key, exp_val in expected.items():
        act_val = actual.get(key)
        if exp_val is None or exp_val == 0:
            continue
        if isinstance(exp_val, list) and not exp_val:
            continue
        if isinstance(exp_val, list):
            if sorted(act_val or []) != sorted(exp_val):
                errors.append(f"{key}: expected {exp_val}, got {act_val}")
        elif act_val != exp_val:
            errors.append(f"{key}: expected {exp_val!r}, got {act_val!r}")

    non_empty_fields = ["cantrips", "spells", "attacks", "equipment", "personality", "ideals", "bonds", "flaws"]
    for key in non_empty_fields:
        val = actual.get(key)
        if not val:
            errors.append(f"{key}: expected non-empty, got {val!r}")

    return errors


# ── Judge ────────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """\
You are evaluating a D&D 5e character creation assistant. Score 1-10 on each criterion.
Respond with ONLY valid JSON (no markdown fences):

{"sheet_accuracy": <1-10>, "rules_knowledge": <1-10>, "ux_quality": <1-10>,
 "completeness": <1-10>, "overall": <1-10>, "notes": "<brief explanation>"}

Criteria:
- sheet_accuracy: Do final sheet values match expected?
- rules_knowledge: Were D&D 5e 2024 rules applied correctly?
- ux_quality: Was the assistant clear and conversational?
- completeness: Were all 8 steps completed with all fields populated?
- overall: Holistic score."""


def judge_conversation(history: list[dict], sheet: CharacterSheet) -> dict:
    trimmed = [{"role": m["role"], "content": m["content"][:500]} for m in history]
    expected_dump = EXPECTED.model_dump(by_alias=True)
    content = (
        f"## Conversation\n{json.dumps(trimmed, indent=2)}\n\n"
        f"## Final Character Sheet\n{sheet.model_dump_json(by_alias=True)}\n\n"
        f"## Expected Values\n{json.dumps(expected_dump, indent=2)}"
    )
    msgs = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": content},
    ]
    for attempt in range(4):
        try:
            resp = completion(model=JUDGE_MODEL, messages=msgs, max_tokens=4096)
            raw = resp.choices[0].message.content if resp.choices else ""
            raw = (raw or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1:
                raise ValueError(f"No JSON in judge response (len={len(raw)}): {raw[:300]}")  # noqa: TRY003
            return json.loads(raw[start : end + 1])
        except Exception:
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    return {}


# ── Main loop ────────────────────────────────────────────────────────────────


def test_wizard_creation() -> None:
    sid: str | None = None
    history: list[dict] = []
    sheet = CharacterSheet()
    failure_reason: str | None = None

    print(f"\n{B}{'═' * 72}{X}")
    print(f"{B}  D&D 5e Wizard Builder — LLM-Driven Eval{X}")
    print(f"{B}  Player: {PLAYER_MODEL}  Judge: {JUDGE_MODEL}{X}")
    print(f"{B}{'═' * 72}{X}\n")

    user_msg = "Hi! I'd like to create a wizard."
    for turn in range(MAX_TURNS):
        print(f"{B}Turn {turn + 1}{X}")
        print(f"  {G}Player:{X} {user_msg}")

        text, sheet_delta, sid = chat(sid, user_msg)
        if sheet_delta:
            sheet = sheet_delta

        history.append({"role": "user", "content": user_msg})
        clean = "\n".join(
            ln for ln in text.splitlines() if not ln.startswith("[ERROR:") and "No message in response" not in ln
        )
        history.append({"role": "assistant", "content": clean})

        for line in text.strip().splitlines()[:15]:
            print(f"  {C}Guide:{X} {line}")
        if len(text.strip().splitlines()) > 15:
            print(f"  {D}  ... ({len(text.strip().splitlines()) - 15} more lines){X}")

        if sheet_delta:
            filled = [k for k, v in sheet.model_dump(by_alias=True).items() if v]
            print(f"  {Y}↳ sheet fields: {filled}{X}")

        print()

        errors = check_sheet(sheet)
        if not errors:
            print(f"{G}All expected sheet fields are correct after {turn + 1} turns!{X}\n")
            break

        try:
            user_msg = player_reply(history, sheet)
        except EvalFailure as exc:
            failure_reason = str(exc)
            print(f"{R}Player aborted: {failure_reason}{X}\n")
            break

        time.sleep(2)
    else:
        print(f"{Y}Hit max turns ({MAX_TURNS}), scoring what we have.{X}\n")

    # ── Sheet check ──────────────────────────────────────────────────────────
    errors = check_sheet(sheet)
    total = len(EXPECTED.model_dump(by_alias=True)) + 8
    passed = total - len(errors)
    print(f"{B}{'─' * 72}{X}")
    print(f"{B}  Sheet Check: {passed}/{total}{X}")
    print(f"{B}{'─' * 72}{X}")
    for err in errors:
        print(f"  {R}✗ {err}{X}")
    if not errors:
        print(f"  {G}✓ All fields match expected values{X}")
    print()

    # ── Judge ────────────────────────────────────────────────────────────────
    print(f"{B}{'─' * 72}{X}")
    print(f"{B}  Judge Scoring  (model: {JUDGE_MODEL}){X}")
    print(f"{B}{'─' * 72}{X}")
    try:
        scores = judge_conversation(history, sheet)
        for key in ("sheet_accuracy", "rules_knowledge", "ux_quality", "completeness", "overall"):
            score = scores.get(key, 0)
            color = G if score >= 7 else Y if score >= 5 else R
            bar = "█" * score + "░" * (10 - score)
            print(f"  {key:<20} {color}{bar}  {score}/10{X}")
        if scores.get("notes"):
            print(f"\n  {D}{scores['notes']}{X}")
    except Exception as exc:
        print(f"  {R}Judge error: {exc}{X}")
        scores = {}

    print(f"{B}{'═' * 72}{X}\n")

    if failure_reason:
        pytest.fail(f"Player LLM aborted: {failure_reason}")

    overall = scores.get("overall", 0)
    assert overall >= 5, f"Overall score {overall}/10 is below threshold (5)"
    assert passed >= total - 3, f"Too many sheet errors: {passed}/{total} ({errors})"


if __name__ == "__main__":
    test_wizard_creation()
