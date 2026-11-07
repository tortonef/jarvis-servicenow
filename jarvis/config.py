import os

from dotenv import load_dotenv
from openai import OpenAI

from jarvis.snow import Snow

load_dotenv()

# ServiceNow knowledge base the docs repository is published to, and where Jarvis drafts new articles
KB_TITLE = os.getenv("JARVIS_KB", "Helios Group IT")


def snow_from_env(search=None):
    """search: "semantic" (default, local embeddings) or "keyword" (no extra dependency)."""
    mode = search or os.getenv("SEARCH", "semantic")
    if mode not in ("semantic", "keyword"):
        raise SystemExit(f"SEARCH must be 'semantic' or 'keyword', not {mode!r}")
    db = semantic = knowledge = None
    if os.getenv("DATABASE_URL"):  # optional: without it Jarvis keeps vectors in memory and skips the audit trail
        from jarvis.db import connect
        db = connect(os.environ["DATABASE_URL"])
    if mode == "semantic":
        from jarvis.semantic import MODEL, SemanticIndex
        store = None
        if db:
            from jarvis.db import VectorStore
            store = VectorStore(db, MODEL)
        semantic = SemanticIndex(store=store)
        if db:  # docs-as-code knowledge base in PostgreSQL, sharing the embedding model
            from jarvis.knowledge import KnowledgeBase
            knowledge = KnowledgeBase(db, semantic.embedder, MODEL)
    snow = Snow(os.environ["SNOW_INSTANCE"], os.environ["SNOW_USER"], os.environ["SNOW_PASSWORD"], semantic, db, knowledge)
    if db:
        from jarvis.db import Executions
        snow.executions = Executions(db)
    return snow


def llm_from_env():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"]), os.environ["LLM_MODEL"]
