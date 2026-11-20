"""Score a summary version against the source data. No LLM involved.

uv run python -m summarizer.evaluate v1-baseline v2-grounded
"""
from __future__ import annotations
import json, re, sys

# How we detect that a summary mentions each red flag (case-insensitive regex).
FLAG_PATTERNS = {
    "status": r"winding[- ]up",
    "audit": r"disclaimer|going concern|material uncertainty",
    "negative_equity": r"negative (total )?equity|equity (deficit|is negative|was negative)|capital deficiency",
    "loss": r"\bloss|losses",
    "revenue_decline": r"(revenue|sales|topline|turnover)[^.]{0,60}(fell|fall|declin|drop|down|contract|shr[ai]n?k|decreas)"
                       r"|(fell|declin|drop|contract|shr[ai]n?k|decreas)[^.]{0,40}(revenue|sales|topline)",
    "negative_cash_flow": r"(operating cash ?flow|cash flow from operations|OCF)[^.]{0,60}(-\s?(RM|MYR)|negative|outflow)"
                          r"|negative operating cash|cash burn",
    "interest_cover": r"interest",
    "leverage": r"leverage|gearing|liabilities[^.]{0,30}equity|debt[- ]to[- ]equity",
    "winding_up_petition": r"winding[- ]up petition|petition to wind",
    "judgment_against": r"judge?ment",
    "pending_lawsuits": r"pending",
    "control_change": r"change (of|in) control|(joined|appointed)[^.]{0,60}(2025|board|recent)|recently appointed|new (majority|director)",
    "no_financials": r"no financial|financial (statements|data)[^.]{0,20}(not|un)available|not (filed|available)",
}
RISKY = r"high risk|significant risk|serious|concern|caution|red flag|distress|warrant"
SAFE = r"no red flags( found)?|none found|\*\*red flags\*\*"  # the v2 section heading is not an alarm
CONTRADICTIONS = {
    "says no litigation but cases exist": (r"no (record of )?(litigation|legal|court)|clean litigation|litigation[- ]free",
                                           lambda c: bool(c["litigation"]["cases"])),
    "says clean audits but an opinion is not clean": (r"(clean|unqualified) audit",
                                                      lambda c: any(y["audit"]["opinion"] != "Unqualified"
                                                                    for y in c["financials"]["years"])),
}
TYPE_PATTERNS = {"Debt recovery": r"debt", "Employment claim": r"employ|staff|salar|wage",
                 "Tenancy dispute": r"tenan|rent|landlord", "Winding-up petition": r"winding",
                 "Breach of contract": r"breach|contract", "Construction dispute": r"construction"}
TURN = r"back in profit|return(ed)? to profit|turnaround|turned around|recover|after (net )?loss|previous(ly)? (net )?loss|prior (net )?loss"
MONEY = re.compile(r"(-)?\s*\b(?:RM|MYR)\s*(-)?\s*([\d,]+(?:\.\d+)?)\s*(k|m|mn|million|bn|billion)?\b", re.I)
PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
DEC = re.compile(r"(?<![\w.,])(-?\d+\.\d+)(?![\d%])")
MULT = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def source_numbers(company: dict, facts: dict | None = None) -> tuple[set[float], set[float]]:
    """All numbers in the record (abs values), the percentages it supports, and
    values we derived ourselves in facts (e.g. litigation totals, thresholds)."""
    nums: set[float] = set()
    def walk(x):
        if isinstance(x, bool): return
        if isinstance(x, (int, float)): nums.add(abs(float(x)))
        elif isinstance(x, dict): [walk(v) for v in x.values()]
        elif isinstance(x, list): [walk(v) for v in x]
    walk(company)
    for fl in (facts or {}).get("flags", []):
        for m in MONEY.finditer(fl["text"]):
            nums.add(float(m.group(3).replace(",", "")) * MULT.get((m.group(4) or "").lower(), 1))
        nums.update(abs(float(x)) for x in re.findall(r"\d+\.\d+", MONEY.sub(" ", fl["text"])))
    pcts = {n * 100 for n in nums if n <= 10} | {n for n in nums if n <= 100}
    years = sorted(company["financials"]["years"], key=lambda y: y["financialYear"])
    for a, b in zip(years, years[1:]):
        for k in ("revenue", "profitAfterTax", "totalEquity", "operatingCashFlow"):
            pa, pb = a["statements"][k], b["statements"][k]
            if pa:
                pcts.add(abs(pb / pa - 1) * 100)
                nums.add(abs(pb - pa))
    if len(years) > 1 and years[0]["statements"]["revenue"]:
        pcts.add(abs(years[-1]["statements"]["revenue"] / years[0]["statements"]["revenue"] - 1) * 100)
    return nums, pcts


def _tol(number: str, unit: float = 1.0) -> float:
    """Half a unit of the last digit written: "5.9m" may be off by 0.05m, "5.94m" by 0.005m."""
    decimals = len(number.split(".")[1]) if "." in number else 0
    return 0.5 * 10 ** -decimals * unit + 1e-9


def check_numbers(text: str, nums: set[float], pcts: set[float]) -> tuple[int, list[str]]:
    found, bad = 0, []
    for m in MONEY.finditer(text):
        raw, unit = m.group(3).replace(",", ""), MULT.get((m.group(4) or "").lower(), 1)
        v, found = float(raw) * unit, found + 1
        if not any(abs(v - n) <= max(_tol(raw, unit), 1) for n in nums):
            bad.append(m.group(0).strip())
    rest = MONEY.sub(" ", text)
    for m in PCT.finditer(rest):
        v, found = abs(float(m.group(1))), found + 1
        if not any(abs(v - p) <= _tol(m.group(1)) + 0.01 for p in pcts):
            bad.append(m.group(0))
    rest = PCT.sub(" ", rest)
    for m in DEC.finditer(rest):
        v, found = abs(float(m.group(1))), found + 1
        if not any(abs(v - n) <= _tol(m.group(1)) for n in nums):
            bad.append(m.group(0))
    return found, bad


def evaluate(version: str) -> dict:
    companies = {c["registrationNumber"]: c for c in map(json.loads, open("data/companies.jsonl"))}
    facts = {f["registrationNumber"]: f for f in map(json.loads, open("outputs/facts.jsonl"))}
    rows = []
    for s in map(json.loads, open(f"summaries/{version}.jsonl")):
        reg, text = s["registrationNumber"], s["summary"]
        c, f = companies[reg], facts[reg]
        flags = [fl for fl in f["flags"] if fl["severity"] in ("high", "medium")]
        missed = [fl["code"] for fl in flags if not re.search(FLAG_PATTERNS[fl["code"]], text, re.I)]
        n_found, bad = check_numbers(text, *source_numbers(c, f))
        contra = [name for name, (pat, cond) in CONTRADICTIONS.items() if re.search(pat, text, re.I) and cond(c)]
        risky = f["verdict"] == "green" and re.search(RISKY, re.sub(SAFE, "", text, flags=re.I), re.I) is not None
        open_types = sorted({k["type"] for k in f["litigation"].get("openAgainst", [])})
        types_missed = [t for t in open_types if not re.search(TYPE_PATTERNS.get(t, re.escape(t)), text, re.I)]
        turnaround = any(fl["code"] == "turnaround" for fl in f["flags"])
        turn_noted = bool(re.search(TURN, text, re.I)) if turnaround else None
        rows.append({"registrationNumber": reg, "verdict": f["verdict"], "flags": [fl["code"] for fl in flags],
                     "missed": missed, "numbers": n_found, "unsupported": bad, "contradictions": contra,
                     "falseAlarm": risky, "words": len(text.split()), "openTypes": open_types, "typesMissed": types_missed,
                     "turnaround": turnaround, "turnaroundNoted": turn_noted})
    with open(f"outputs/eval_{version}.jsonl", "w") as out:
        for r in rows:
            out.write(json.dumps(r) + "\n")
    total_flags = sum(len(r["flags"]) for r in rows)
    high = [(fl, r) for r in rows for fl in facts[r["registrationNumber"]]["flags"] if fl["severity"] == "high"]
    nums = sum(r["numbers"] for r in rows)
    greens = [r for r in rows if r["verdict"] == "green"]
    return {
        "companies": len(rows),
        "flag recall": 1 - sum(len(r["missed"]) for r in rows) / total_flags if total_flags else 1,
        "high-flag recall": 1 - sum(fl["code"] in r["missed"] for fl, r in high) / len(high) if high else 1,
        "numbers checked": nums,
        "number accuracy": 1 - sum(len(r["unsupported"]) for r in rows) / nums if nums else 1,
        "contradictions": sum(len(r["contradictions"]) for r in rows),
        "false alarms (green)": f"{sum(r['falseAlarm'] for r in greens)}/{len(greens)}",
        "turnaround noted": f"{sum(bool(r['turnaroundNoted']) for r in rows if r['turnaround'])}/{sum(r['turnaround'] for r in rows)}",
        "lit. types named": 1 - sum(len(r["typesMissed"]) for r in rows) / max(1, sum(len(r["openTypes"]) for r in rows)),
        "avg words": sum(r["words"] for r in rows) / len(rows),
        "max words": max(r["words"] for r in rows),
    }


if __name__ == "__main__":
    results = {v: evaluate(v) for v in sys.argv[1:]}
    keys = list(next(iter(results.values())))
    print(f"{'metric':22s}" + "".join(f"{v:>16s}" for v in results))
    for k in keys:
        cells = [results[v][k] for v in results]
        print(f"{k:22s}" + "".join(f"{x:>16.2f}" if isinstance(x, float) else f"{str(x):>16s}" for x in cells))
