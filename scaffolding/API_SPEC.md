# API Specification

The frontend (`index.html`) communicates with the backend (`app.py`) over HTTP. The backend serves the frontend as a static file and exposes two API endpoints for chat and session management.

## Endpoints

### `GET /`

Serves the `index.html` frontend.

### `POST /chat`

Send a user message and receive a streamed response.

#### Request

```json
{
    "message": "string (required)",
    "session_id": "string | null"
}
```

If `session_id` is `null` or omitted, the backend creates a new session.

#### Response

**Content-Type:** `text/event-stream`

The response is a Server-Sent Events (SSE) stream. The frontend reads it using the Fetch API with `ReadableStream` (not `EventSource`, since this is a POST request).

#### SSE Event Types

##### `session`

Sent first, always. Contains the session ID for the conversation.

```
event: session
data: <session-id-string>
```

The frontend stores this in `localStorage` and sends it with subsequent requests.

##### `message` (default)

Chat text from the assistant. Sent as one or more chunks. No `event:` line — the default SSE event type is `message`.

```
data: Hello, I am the Wizard Builder guide.
```

```
data: I'll help you create
```

```
data:  a Level 1 Wizard.
```

The frontend appends each `data` payload to the current assistant message and renders it as Markdown (via `marked.js`).

##### `character_sheet`

A JSON blob representing the character sheet state. This event is **not** shown in the chat — the frontend intercepts it and updates the character sheet pane.

```
event: character_sheet
data: {"name":"Elara","race":"Elf","str":8,"dex":14,...}
```

The JSON object can contain any subset of the character sheet fields. The frontend merges incoming fields into its local state, so the backend can send incremental updates (e.g., just `{"name": "Aldric"}` after the user picks a name).

### `POST /clear`

Clear a chat session's history.

#### Request

```json
{
    "session_id": "string (required)"
}
```

#### Response

```json
{
    "status": "ok"
}
```

---

## SSE Stream Format

SSE events are separated by double newlines (`\n\n`). Each event consists of optional `event:` and `data:` lines:

```
event: <event-type>\n
data: <payload>\n
\n
```

If the `event:` line is omitted, the event type defaults to `message`.

Multi-line data uses multiple `data:` lines (the frontend concatenates them):

```
data: first part\n
data: second part\n
\n
```

---

## Character Sheet Data Model

The `character_sheet` SSE event sends a JSON object with these fields. All fields are optional in any individual update — the frontend merges them into its state.

| Field | Type | Description |
|---|---|---|
| `name` | `string` | Character name |
| `race` | `string` | Species (e.g., "Elf", "Human", "Dwarf") |
| `background` | `string` | Background (e.g., "Sage", "Acolyte") |
| `alignment` | `string` | Alignment (e.g., "Neutral Good") |
| `str` | `int` | Strength score (1-20) |
| `dex` | `int` | Dexterity score (1-20) |
| `con` | `int` | Constitution score (1-20) |
| `int` | `int` | Intelligence score (1-20) |
| `wis` | `int` | Wisdom score (1-20) |
| `cha` | `int` | Charisma score (1-20) |
| `ac` | `int` | Armor Class (10 + DEX mod, or 13 + DEX with Mage Armor) |
| `speed` | `int` | Speed in feet (default 30) |
| `hp_max` | `int` | Maximum hit points (6 + CON modifier at level 1) |
| `save_profs` | `string[]` | Saving throw proficiencies, e.g. `["int", "wis"]` |
| `skill_profs` | `string[]` | Skill proficiencies, e.g. `["arcana", "history"]` |
| `cantrips` | `object[]` | Cantrips: `[{name, hit?, damage?}]` |
| `spells` | `object[]` | Spells: `[{name, level, school, ritual?, concentration?, description?}]` |
| `attacks` | `object[]` | Weapon attacks: `[{name, hit, damage}]` |
| `features` | `string[]` | Class features, e.g. `["Spellcasting", "Ritual Adept", "Arcane Recovery"]` |
| `personality` | `string` | Personality traits |
| `ideals` | `string` | Ideals |
| `bonds` | `string` | Bonds |
| `flaws` | `string` | Flaws |

### Cantrip Object

```json
{
    "name": "Fire Bolt",
    "hit": "+5",
    "damage": "1d10 fire"
}
```

`hit` and `damage` are optional — utility cantrips like Mage Hand omit them.

### Prepared Spell Object

```json
{
    "name": "Mage Armor",
    "level": 1,
    "school": "Abjuration",
    "ritual": false,
    "concentration": false,
    "description": "AC becomes 13 + DEX mod"
}
```

### Weapon Attack Object

```json
{
    "name": "Quarterstaff",
    "hit": "-1",
    "damage": "1d6-1 bludg."
}
```

---

## Frontend Computed Values

The frontend computes the following values from the character sheet data rather than receiving them from the backend:

| Value | Formula |
|---|---|
| Ability modifier | `floor((score - 10) / 2)` |
| Proficiency bonus | `+2` (fixed at level 1) |
| Saving throw bonus | `ability modifier + 2 (if proficient)` |
| Skill bonus | `ability modifier + 2 (if proficient)` |
| Initiative | `DEX modifier` |
| Spell Save DC | `8 + 2 + INT modifier` |
| Spell Attack Bonus | `2 + INT modifier` |
| Passive Perception | `10 + WIS modifier + 2 (if proficient in Perception)` |

---

## Session Management

- Sessions are identified by UUID strings.
- The frontend stores `session_id` in `localStorage`.
- The backend maintains conversation history per session (in memory).
- The `POST /clear` endpoint deletes a session's history.
- The Clear button in the UI calls `/clear` and resets local state.
