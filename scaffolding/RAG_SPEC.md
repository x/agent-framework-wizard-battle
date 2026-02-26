# RAG Specification

The indexing pipeline (`indexing_pipeline.py`) chunks the 2024 Player's Handbook markdown sources and stores them in a ChromaDB database at `chroma_db/`. Run it before starting the server:

```bash
uv run python indexing_pipeline.py
```

## ChromaDB Setup

```python
import chromadb

client = chromadb.PersistentClient(path="chroma_db")
collection = client.get_collection("spells")
results = collection.query(query_texts=["fire damage ranged"], n_results=3)
```

Each result includes `ids`, `documents` (the full markdown chunk), `metadatas` (with `title` and `source` keys), and `distances` (cosine).

## Collections

| Collection | Description | Example Titles | Chunks |
|---|---|---|---|
| `classes` | Full class entries (traits, features, subclasses) | `Wizard`, `Fighter`, `Cleric` | 12 |
| `backgrounds` | Background entries (ability scores, feat, skills, equipment) | `Sage`, `Acolyte`, `Criminal` | 17 |
| `species` | Species entries (traits, size, speed, special abilities) | `Elf`, `Human`, `Dragonborn` | 10 |
| `feats` | Individual feats across all categories | `Alert`, `War Caster`, `Lucky` | 76 |
| `equipment` | Equipment sections (weapons table, armor table, tools, adventuring gear) | `Weapons`, `Armor`, `Tools` | 9 |
| `spells` | Individual spell descriptions (casting time, range, components, effects) | `Fire Bolt`, `Mage Armor`, `Shield` | 369 |
| `rules` | General rules and glossary definitions | `Combat`, `D20 Tests`, `Concentration` | 169 |

## Metadata

Every document has:

- `title` — the heading or name of the chunk (e.g., `"Fire Bolt"`, `"Elf"`, `"Sage"`)
- `source` — the source filename (e.g., `"07-spells.md"`, `"04-character-origins.md"`)

## Embedding Model

ChromaDB's default embedding function (Sentence Transformers `all-MiniLM-L6-v2`) is used. No API keys required.
