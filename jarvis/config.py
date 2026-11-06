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
    semantic = None
    if mode == "semantic":
        from jarvis.semantic import SemanticIndex
        semantic = SemanticIndex()
    return Snow(os.environ["SNOW_INSTANCE"], os.environ["SNOW_USER"], os.environ["SNOW_PASSWORD"], semantic)


def llm_from_env():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"]), os.environ["LLM_MODEL"]
