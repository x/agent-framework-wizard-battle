# Agent Framework Wizard Battle

A head-to-head comparison of every major Python LLM agent framework, all tackling the same challenge: **guiding a user through building a 5e (2024) Level 1 D&D Wizard.**

Each framework implements the same agent as a web server with the same shared frontend, deployed side-by-side in this repo for direct comparison.

## The Challenge

Each framework must serve the frontend chat interface that displays the conversation and updates the Character Sheet in real-time.

### What We're Testing

1. **Conversation Handling** — Managing conversation history between agent and user.
2. **Few-Shot Examples** — Concrete examples of desired agent behavior at each step of the wizard-building process.
3. **Tool Calling** — Dice rolling is handled by tools, not the LLM.
4. **Retrieval Augmented Generation** — Race and spell information surfaced into context based on user questions.
5. **Multi-Step Orchestration** — Each step of building a wizard has its own prompt, behavior examples, and available tools (e.g., assigning ability scores vs. building a spellbook).
6. **State Management** — The character sheet is a Pydantic model with validation preventing illegal states (e.g., picking a level 2 spell).

### Shared Infrastructure

- **Frontend:** Single-page `index.html`, shared across all agents.
- **Communication:** HTTP + SSE. Two endpoints per agent: one for chat, one for the character sheet.
- **LLM Backend:** All frameworks communicate with models via the LiteLLM Python SDK, making them equally model-agnostic.

## The Frameworks

- OpenAI Agents SDK
- Anthropic Agent SDK (Claude)
- Google ADK
- LangGraph
- CrewAI
- PydanticAI
