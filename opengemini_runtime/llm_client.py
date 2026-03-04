import json
import os
from openai import OpenAI


SYSTEM_PROMPT = """
너는 OpenGemini 기반 에이전트다.
반드시 아래 JSON 중 하나만 출력하라(코드블록 금지):
1) {"type":"reply","text":"..."}
2) {"type":"tool","tool":"list_dir|read_file|write_file|edit_replace|memory_add|memory_search","args":{...}}
""".strip()


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            base_url=os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        self.model = os.getenv("OPENAI_MODEL", "gemini-2.5-flash")

    def decide(self, messages):
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        )
        text = resp.choices[0].message.content.strip()
        return json.loads(text)
