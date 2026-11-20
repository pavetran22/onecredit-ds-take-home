"""Gemini calls with retries, and an on-disk cache of every response.

Cached responses mean we can re-score or re-run without calling the model again.
"""
from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
MODEL = os.environ.get("SUMMARY_MODEL", "gemini-3.5-flash")
CACHE = Path("outputs/llm_cache")
CACHE.mkdir(parents=True, exist_ok=True)
_client = None


def generate(prompt: str, system: str = "", model: str = MODEL, temperature: float = 0.2) -> str:
    key = hashlib.sha256(json.dumps([model, system, prompt, temperature]).encode()).hexdigest()[:16]
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())["text"]
    global _client
    _client = _client or genai.Client(http_options=types.HttpOptions(timeout=180_000))
    for attempt in range(6):
        try:
            r = _client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system or None, temperature=temperature))
            u = r.usage_metadata
            path.write_text(json.dumps({
                "model": model, "system": system, "prompt": prompt, "text": r.text or "",
                "usage": {"input": u.prompt_token_count, "output": u.candidates_token_count} if u else None,
            }, indent=1))
            return r.text or ""
        except Exception as e:  # busy (503), timeout (504), rate limit (429)
            wait = min(60, 5 * 2 ** attempt)
            print(f"   {model}: {str(e)[:70]} -> retry in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"{model} failed after retries")
