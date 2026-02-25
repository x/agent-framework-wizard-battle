"""Pydantic models for a Level 1 D&D 5e (2024) character sheet."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Enums ──


class Ability(StrEnum):
    """The six ability scores."""

    STR = "str"
    DEX = "dex"
    CON = "con"
    INT = "int"
    WIS = "wis"
    CHA = "cha"


class Skill(StrEnum):
    """All 18 skills."""

    ACROBATICS = "acrobatics"
    ANIMAL_HANDLING = "animal_handling"
    ARCANA = "arcana"
    ATHLETICS = "athletics"
    DECEPTION = "deception"
    HISTORY = "history"
    INSIGHT = "insight"
    INTIMIDATION = "intimidation"
    INVESTIGATION = "investigation"
    MEDICINE = "medicine"
    NATURE = "nature"
    PERCEPTION = "perception"
    PERFORMANCE = "performance"
    PERSUASION = "persuasion"
    RELIGION = "religion"
    SLEIGHT_OF_HAND = "sleight_of_hand"
    STEALTH = "stealth"
    SURVIVAL = "survival"


SKILL_ABILITIES: dict[Skill, Ability] = {
    Skill.ACROBATICS: Ability.DEX,
    Skill.ANIMAL_HANDLING: Ability.WIS,
    Skill.ARCANA: Ability.INT,
    Skill.ATHLETICS: Ability.STR,
    Skill.DECEPTION: Ability.CHA,
    Skill.HISTORY: Ability.INT,
    Skill.INSIGHT: Ability.WIS,
    Skill.INTIMIDATION: Ability.CHA,
    Skill.INVESTIGATION: Ability.INT,
    Skill.MEDICINE: Ability.WIS,
    Skill.NATURE: Ability.INT,
    Skill.PERCEPTION: Ability.WIS,
    Skill.PERFORMANCE: Ability.CHA,
    Skill.PERSUASION: Ability.CHA,
    Skill.RELIGION: Ability.INT,
    Skill.SLEIGHT_OF_HAND: Ability.DEX,
    Skill.STEALTH: Ability.DEX,
    Skill.SURVIVAL: Ability.WIS,
}


WIZARD_SKILL_CHOICES: list[Skill] = [
    Skill.ARCANA,
    Skill.HISTORY,
    Skill.INSIGHT,
    Skill.INVESTIGATION,
    Skill.MEDICINE,
    Skill.NATURE,
    Skill.RELIGION,
]


class Alignment(StrEnum):
    """The nine alignments."""

    LAWFUL_GOOD = "Lawful Good"
    NEUTRAL_GOOD = "Neutral Good"
    CHAOTIC_GOOD = "Chaotic Good"
    LAWFUL_NEUTRAL = "Lawful Neutral"
    NEUTRAL = "Neutral"
    CHAOTIC_NEUTRAL = "Chaotic Neutral"
    LAWFUL_EVIL = "Lawful Evil"
    NEUTRAL_EVIL = "Neutral Evil"
    CHAOTIC_EVIL = "Chaotic Evil"


class Species(StrEnum):
    """Playable species from the 2024 PHB."""

    AASIMAR = "Aasimar"
    DRAGONBORN = "Dragonborn"
    DWARF = "Dwarf"
    ELF = "Elf"
    GNOME = "Gnome"
    GOLIATH = "Goliath"
    HALFLING = "Halfling"
    HUMAN = "Human"
    ORC = "Orc"
    TIEFLING = "Tiefling"


class Background(StrEnum):
    """Backgrounds from the 2024 PHB."""

    ACOLYTE = "Acolyte"
    ARTISAN = "Artisan"
    CHARLATAN = "Charlatan"
    CRIMINAL = "Criminal"
    ENTERTAINER = "Entertainer"
    FARMER = "Farmer"
    GUARD = "Guard"
    GUIDE = "Guide"
    HERMIT = "Hermit"
    MERCHANT = "Merchant"
    NOBLE = "Noble"
    SAGE = "Sage"
    SAILOR = "Sailor"
    SCRIBE = "Scribe"
    SOLDIER = "Soldier"
    WAYFARER = "Wayfarer"


class SpellSchool(StrEnum):
    """Schools of magic."""

    ABJURATION = "Abjuration"
    CONJURATION = "Conjuration"
    DIVINATION = "Divination"
    ENCHANTMENT = "Enchantment"
    EVOCATION = "Evocation"
    ILLUSION = "Illusion"
    NECROMANCY = "Necromancy"
    TRANSMUTATION = "Transmutation"


class DamageType(StrEnum):
    """Damage types."""

    ACID = "Acid"
    BLUDGEONING = "Bludgeoning"
    COLD = "Cold"
    FIRE = "Fire"
    FORCE = "Force"
    LIGHTNING = "Lightning"
    NECROTIC = "Necrotic"
    PIERCING = "Piercing"
    POISON = "Poison"
    PSYCHIC = "Psychic"
    RADIANT = "Radiant"
    SLASHING = "Slashing"
    THUNDER = "Thunder"


# ── Sub-Models ──


class AbilityScores(BaseModel):
    """The six ability scores (before or after racial/background adjustments)."""

    model_config = ConfigDict(populate_by_name=True)

    strength: int = Field(ge=1, le=20, serialization_alias="str")
    dexterity: int = Field(ge=1, le=20, serialization_alias="dex")
    constitution: int = Field(ge=1, le=20, serialization_alias="con")
    intelligence: int = Field(ge=1, le=20, serialization_alias="int")
    wisdom: int = Field(ge=1, le=20, serialization_alias="wis")
    charisma: int = Field(ge=1, le=20, serialization_alias="cha")


class Weapon(BaseModel):
    """A weapon the character carries."""

    name: str
    damage: str
    damage_type: DamageType
    properties: list[str] = Field(default_factory=list)


class SpellSlots(BaseModel):
    """Spell slot tracking."""

    level_1: int = Field(ge=0)


class Spell(BaseModel):
    """A spell known or prepared by the wizard."""

    name: str
    level: Literal[0, 1]
    school: SpellSchool
    ritual: bool = False
    concentration: bool = False
    description: str = ""


class CantripEntry(BaseModel):
    """A cantrip displayed in the character sheet attacks section."""

    name: str
    hit: str | None = None
    damage: str | None = None


class WeaponEntry(BaseModel):
    """A weapon attack displayed in the character sheet attacks section."""

    name: str
    hit: str
    damage: str


# ── Character Sheet (top-level model, matches the frontend data contract) ──


class CharacterSheet(BaseModel):
    """Complete Level 1 character sheet.

    Field names use serialization aliases to match the keys expected by the
    frontend Alpine.js component (``str``, ``int``, etc.). The backend sends
    this (or a partial subset) as a JSON blob via the ``character_sheet`` SSE
    event, and the frontend merges it into its state.
    """

    model_config = ConfigDict(populate_by_name=True)

    # Identity
    name: str
    species: Species
    background: Background
    alignment: Alignment

    # Ability scores (after background adjustments) — aliased to match frontend
    strength: int = Field(ge=1, le=20, serialization_alias="str")
    dexterity: int = Field(ge=1, le=20, serialization_alias="dex")
    constitution: int = Field(ge=1, le=20, serialization_alias="con")
    intelligence: int = Field(ge=1, le=20, serialization_alias="int")
    wisdom: int = Field(ge=1, le=20, serialization_alias="wis")
    charisma: int = Field(ge=1, le=20, serialization_alias="cha")

    # Combat
    ac: int
    speed: int = 30
    hp_max: int

    # Proficiencies
    save_profs: list[Ability]
    skill_profs: list[Skill]

    # Spellcasting
    cantrips: list[CantripEntry]
    spells: list[Spell]
    spellbook: list[Spell]

    # Weapons
    attacks: list[WeaponEntry]

    # Class features
    features: list[str]

    # Personality (from background / player choice)
    personality: str | None = None
    ideals: str | None = None
    bonds: str | None = None
    flaws: str | None = None

    # Equipment
    equipment: list[str] = Field(default_factory=list)
    gp: int = 0
