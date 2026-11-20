"""Prompt builders, one per summary version."""
import json
from summarizer.facts import rm

AUDIENCE = ("You write company summaries for a team that vets companies before choosing them "
            "as suppliers or project partners. Data is as of 31 December 2025.")


def v1_baseline(company: dict, facts: dict) -> tuple[str, str]:
    """Baseline: the raw record, a generic instruction."""
    return AUDIENCE, ("Summarise this company in under 150 words of Markdown.\n\n```json\n"
                      + json.dumps(company, indent=1) + "\n```")


VERDICT = {"red": "🔴 High risk", "amber": "🟠 Some concerns", "green": "🟢 No red flags found"}

V2_RULES = """Write the summary in Markdown using EXACTLY this layout:

**<VERDICT, copied exactly>**
**<companyName>** · <industry> · <state> · incorporated <year> (<ageYears> years) · <status>
<One sentence: what the company does, and its largest shareholder with %. Say "controlled by" only if above 50%.>

**Red flags**
- <one bullet per item in RED_FLAGS, same order, keeping every number exactly as given>
(If RED_FLAGS is empty, write "- None found in the record.")

**Financials**
<One or two sentences on the latest financial year (write it as FY<year>): revenue, profit after tax, revenue trend and operating
cash flow, using the given values. If financials is null, write "No financial statements on record.">

**Also note**
- <one bullet per item in NOTES; leave out this whole section if NOTES is empty>

Rules:
- Use only the facts provided. Do not add risks, opinions or recommendations that are not in them.
- Every item in RED_FLAGS must appear. Do not soften, merge away or drop any.
- Copy money values exactly as given (e.g. RM5.35m, -RM819k). Never write MYR.
- Missing (null) ratios are normal; do not mention them.
- Write changes once, e.g. "down 9%" or "up 2%", never "down -9%".
- Maximum 150 words."""


def v2_grounded(company: dict, facts: dict) -> tuple[str, str]:
    """Grounded: the LLM only writes up pre-computed facts and flags, in a fixed layout."""
    fin = facts["financials"]
    view = None
    if fin:
        growth = fin.get("revenueGrowth")
        view = {"latestYear": fin["latestYear"], "yearsAvailable": fin["yearsAvailable"],
                "revenue": rm(fin["revenue"]), "profitAfterTax": rm(fin["profitAfterTax"]),
                "revenueChangeVsPriorYear": f"{growth:+.0%}" if growth is not None else "n/a",
                "operatingCashFlow": rm(fin["operatingCashFlow"]),
                "revenueByYear": {h["year"]: rm(h["revenue"]) for h in fin["history"]},
                "profitAfterTaxByYear": {h["year"]: rm(h["profitAfterTax"]) for h in fin["history"]}}
    payload = {
        "VERDICT": VERDICT[facts["verdict"]],
        "company": {k: facts[k] for k in ("companyName", "industry", "state", "incorporationDate",
                                          "ageYears", "status", "natureOfBusiness")},
        "topShareholder": facts["topShareholder"],
        "financials": view,
        "litigation": facts["litigation"],
        "RED_FLAGS": [f["text"] for f in facts["flags"] if f["severity"] in ("high", "medium")],
        "NOTES": [f["text"] for f in facts["flags"] if f["severity"] == "info"],
    }
    return AUDIENCE + "\n\n" + V2_RULES, "```json\n" + json.dumps(payload, indent=1, ensure_ascii=False) + "\n```"


VERSIONS = {"v1-baseline": v1_baseline, "v2-grounded": v2_grounded}
