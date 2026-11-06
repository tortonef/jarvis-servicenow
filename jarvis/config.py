import os

from dotenv import load_dotenv
from openai import OpenAI

from jarvis.snow import Snow

load_dotenv()


def snow_from_env():
    return Snow(os.environ["SNOW_INSTANCE"], os.environ["SNOW_USER"], os.environ["SNOW_PASSWORD"])


def llm_from_env():
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"]), os.environ["LLM_MODEL"]
