"""Index PHB 2024 markdown sources into ChromaDB collections for RAG."""

import re
from collections.abc import Callable
from pathlib import Path

import chromadb

SOURCES = Path(__file__).resolve().parent.parent / "sources" / "phb-2024"
DB_PATH = Path(__file__).resolve().parent / "chroma_db"

type Chunker = Callable[[str], list[tuple[str, str]]]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_section(text: str, heading: str) -> str:
    """Extract everything under a heading until the next heading of equal or higher level."""
    pattern = rf"^##?\s+{re.escape(heading)}\s*$"
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        msg = f"Section '{heading}' not found"
        raise ValueError(msg)
    level = m.group().count("#", 0, m.group().index(" "))
    rest = text[m.end() :]
    end = re.search(rf"^{'#' * level}(?!#)\s", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _split_by_heading(text: str, level: int) -> list[tuple[str, str]]:
    """Split markdown into chunks at headings of a given level."""
    prefix = "#" * level
    pattern = rf"^{prefix}(?!#)\s+(.+)$"
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(1).strip()
        body = text[start:end].strip()
        if body:
            chunks.append((title, body))
    return chunks


def _split_by_hr(text: str, heading_level: int = 3) -> list[tuple[str, str]]:
    """Split markdown into chunks at horizontal rules, using headings as titles."""
    blocks = re.split(r"\n---\n", text)
    prefix = "#" * heading_level
    pattern = rf"^{prefix}(?!#)\s+(.+)$"
    chunks = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m = re.search(pattern, block, re.MULTILINE)
        title = m.group(1).strip() if m else block[:80].strip()
        chunks.append((title, block))
    return chunks


def chunk_classes(text: str) -> list[tuple[str, str]]:
    """Split classes file by ## headings (one per class)."""
    return _split_by_heading(text, level=2)


def chunk_backgrounds(text: str) -> list[tuple[str, str]]:
    """Extract Background Descriptions section, split by ---."""
    section = _extract_section(text, "Background Descriptions")
    return _split_by_hr(section, heading_level=3)


def chunk_species(text: str) -> list[tuple[str, str]]:
    """Extract Species Descriptions section, split by --- or ### heading."""
    section = _extract_section(text, "Species Descriptions")
    return _split_by_heading(section, level=3)


def chunk_feats(text: str) -> list[tuple[str, str]]:
    """Split feats by --- separators."""
    return _split_by_hr(text, heading_level=3)


def chunk_equipment(text: str) -> list[tuple[str, str]]:
    """Split equipment by ## headings (Weapons, Armor, Tools, etc.)."""
    return _split_by_heading(text, level=2)


def chunk_spells(text: str) -> list[tuple[str, str]]:
    """Extract Spell Descriptions section, split by ---."""
    section = _extract_section(text, "Spell Descriptions")
    return _split_by_hr(section, heading_level=3)


def chunk_rules_playing(text: str) -> list[tuple[str, str]]:
    """Split playing-the-game rules by ## headings."""
    return _split_by_heading(text, level=2)


def chunk_rules_glossary(text: str) -> list[tuple[str, str]]:
    """Split rules glossary by --- separators."""
    section = _extract_section(text, "Rules Definitions")
    return _split_by_hr(section, heading_level=3)


CHUNKERS: dict[str, list[tuple[Path, Chunker]]] = {
    "classes": [(SOURCES / "03-character-classes.md", chunk_classes)],
    "backgrounds": [(SOURCES / "04-character-origins.md", chunk_backgrounds)],
    "species": [(SOURCES / "04-character-origins.md", chunk_species)],
    "feats": [(SOURCES / "05-feats.md", chunk_feats)],
    "equipment": [(SOURCES / "06-equipment.md", chunk_equipment)],
    "spells": [(SOURCES / "07-spells.md", chunk_spells)],
    "rules": [
        (SOURCES / "01-playing-the-game.md", chunk_rules_playing),
        (SOURCES / "app-b-rules-glossary.md", chunk_rules_glossary),
    ],
}


def build_index() -> None:
    """Build all ChromaDB collections from PHB sources."""
    client = chromadb.PersistentClient(path=str(DB_PATH))

    for collection_name, sources in CHUNKERS.items():
        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        if collection.count() > 0:
            collection.delete(where={"source": {"$ne": ""}})

        all_ids: list[str] = []
        all_docs: list[str] = []
        all_meta: list[dict[str, str]] = []

        for path, chunker in sources:
            text = _read(path)
            chunks = chunker(text)
            for title, body in chunks:
                doc_id = f"{collection_name}:{path.stem}:{title}"
                all_ids.append(doc_id)
                all_docs.append(body)
                all_meta.append({"title": title, "source": path.name})

        if all_ids:
            collection.add(ids=all_ids, documents=all_docs, metadatas=all_meta)  # type: ignore[arg-type]

        print(f"  {collection_name}: {len(all_ids)} chunks")  # noqa: T201


if __name__ == "__main__":
    print("Building PHB 2024 index...")  # noqa: T201
    build_index()
    print("Done.")  # noqa: T201
