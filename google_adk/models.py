"""Pydantic models for a Level 1 D&D 5e (2024) character sheet."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


def validate_character_name(name: str) -> str:
    """Validate and normalize a character name. Raises ValueError if invalid."""
    words = name.strip().split()
    if len(words) < 2:
        raise ValueError(  # noqa: TRY003
            f"A character name must be at least two words (e.g., 'Aldric Dawnwhisper'). "
            f"'{name.strip()}' is only one word — try adding a surname or title "
            f"(e.g., '{name.strip()} Stormblade')."
        )
    return name.strip()


_ELF_SUBTYPES = frozenset({"High Elf", "Wood Elf", "Drow"})


def validate_background(background: str) -> str:
    """Validate a background name. Raises ValueError if invalid."""
    try:
        return Background(background).value
    except ValueError:
        valid = ", ".join(b.value for b in Background)
        raise ValueError(f"'{background}' is not a valid background. Choose from: {valid}") from None  # noqa: TRY003


def validate_species(species: str) -> str:
    """Validate a species name (including Elf subtypes). Raises ValueError if invalid."""
    if species in _ELF_SUBTYPES:
        return species
    try:
        return Species(species).value
    except ValueError:
        valid = ", ".join(s.value for s in Species)
        raise ValueError(  # noqa: TRY003
            f"'{species}' is not a valid species. Choose from: {valid}. Elf subtypes: High Elf, Wood Elf, Drow."
        ) from None


def validate_alignment(alignment: str) -> str:
    """Validate an alignment name. Raises ValueError if invalid."""
    normalized = "Neutral" if alignment == "True Neutral" else alignment
    try:
        return Alignment(normalized).value
    except ValueError:
        valid = ", ".join(a.value for a in Alignment)
        raise ValueError(f"'{alignment}' is not a valid alignment. Choose from: {valid}") from None  # noqa: TRY003


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
    """Level 1 character sheet that can be built incrementally.

    All fields default to None/empty so an empty sheet can be created at the
    start of character creation and filled in step by step. Field names and
    serialization aliases match the frontend's EMPTY_CHARACTER contract.
    """

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    name: str | None = None
    race: str | None = None
    background: str | None = None
    alignment: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        return validate_character_name(v) if v else v

    @field_validator("race", mode="before")
    @classmethod
    def _validate_race(cls, v: str | None) -> str | None:
        return validate_species(v) if v else v

    @field_validator("background", mode="before")
    @classmethod
    def _validate_background(cls, v: str | None) -> str | None:
        return validate_background(v) if v else v

    @field_validator("alignment", mode="before")
    @classmethod
    def _validate_alignment(cls, v: str | None) -> str | None:
        return validate_alignment(v) if v else v

    strength: int | None = Field(default=None, alias="str")
    dexterity: int | None = Field(default=None, alias="dex")
    constitution: int | None = Field(default=None, alias="con")
    intelligence: int | None = Field(default=None, alias="int")
    wisdom: int | None = Field(default=None, alias="wis")
    charisma: int | None = Field(default=None, alias="cha")

    ac: int | None = None
    speed: int | None = None
    hp_max: int | None = None

    save_profs: list[str] = Field(default_factory=list)
    skill_profs: list[str] = Field(default_factory=list)

    cantrips: list[str] = Field(default_factory=list)
    spells: list[str] = Field(default_factory=list)

    attacks: list[dict[str, str]] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)

    personality: str | None = None
    ideals: str | None = None
    bonds: str | None = None
    flaws: str | None = None

    equipment: list[str] = Field(default_factory=list)
    gp: int = 0
