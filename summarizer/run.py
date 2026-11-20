"""Generate summaries: uv run python -m summarizer.run <version> [limit]"""
import json, sys
from pathlib import Path
from summarizer.llm import generate
from summarizer.prompts import VERSIONS


def main(version: str, limit: int | None = None) -> None:
    build = VERSIONS[version]
    companies = [json.loads(l) for l in open("data/companies.jsonl")][:limit]
    facts = {f["registrationNumber"]: f for f in map(json.loads, open("outputs/facts.jsonl"))}
    out = Path("summaries") / f"{version}.jsonl"
    with out.open("w") as f:
        for i, c in enumerate(companies, 1):
            system, prompt = build(c, facts[c["registrationNumber"]])
            text = generate(prompt, system).strip()
            f.write(json.dumps({"registrationNumber": c["registrationNumber"], "summary": text}) + "\n")
            print(f"[{i}/{len(companies)}] {c['registrationNumber']} ({len(text.split())} words)", flush=True)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
