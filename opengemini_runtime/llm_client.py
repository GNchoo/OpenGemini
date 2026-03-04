import json
import os
import subprocess
from openai import OpenAI


SYSTEM_PROMPT = """
너는 OpenGemini 기반 에이전트다.
반드시 아래 JSON 중 하나만 출력하라(코드블록 금지):
1) {"type":"reply","text":"..."}
2) {"type":"tool","tool":"list_dir|read_file|write_file|edit_replace|memory_add|memory_search","args":{...}}
""".strip()


class LLMClient:
    def __init__(self):
        self.base_url = os.getenv("OPENAI_BASE_URL")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gemini-2.5-flash")
        self.gemini_bin = os.getenv("GEMINI_BIN", "/home/linuxbrew/.linuxbrew/bin/gemini")

        self.client = None
        if self.base_url and self.api_key:
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def _decide_via_gemini_cli(self, messages):
        convo = "\n".join([f"[{m['role']}] {m['content']}" for m in messages])
        prompt = f"{SYSTEM_PROMPT}\n\n대화:\n{convo}\n\nJSON만 출력해." 
        proc = subprocess.run(
            [self.gemini_bin, "-m", self.model, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        return json.loads(out)

    def decide(self, messages):
        if self.client is None:
            return self._decide_via_gemini_cli(messages)

        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        )
        text = resp.choices[0].message.content.strip()
        return json.loads(text)
