import os

from dotenv import load_dotenv
from openai import OpenAI

from jarvis.snow import Snow

load_dotenv()

# Knowledge base where the demo articles live and where Jarvis drafts new ones
KB_TITLE = os.getenv("JARVIS_KB", "IT Service Desk (Jarvis demo)")


def snow_from_env(search=None):
    """search: "semantic" (default, local embeddings) or "keyword" (no extra dependency)."""
    mode = search or os.getenv("SEARCH", "semantic")
    if mode not in ("semantic", "keyword"):
        raise SystemExit(f"SEARCH must be 'semantic' or 'keyword', not {mode!r}")
    db = semantic = None
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
    return Snow(os.environ["SNOW_INSTANCE"], os.environ["SNOW_USER"], os.environ["SNOW_PASSWORD"], semantic, db)


def llm_from_env():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"]), os.environ["LLM_MODEL"]
