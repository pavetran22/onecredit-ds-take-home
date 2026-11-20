"""Deterministic facts and red flags for each company (no LLM).

Everything a summary may state is computed here, so the LLM only writes,
and every claim can be checked against this output.
"""
from __future__ import annotations
import json
from datetime import date

AS_OF = date(2025, 12, 31)  # the dataset is "as of 31 December 2025"
SEVERITY = {"high": 0, "medium": 1, "info": 2}


def rm(x: float | None) -> str:
    if x is None:
        return "n/a"
    sign, x = ("-" if x < 0 else ""), abs(x)
    return f"{sign}RM{x/1e6:.2f}m" if x >= 1e6 else f"{sign}RM{x/1e3:.0f}k"


def days_ago(s: str | None) -> int | None:
    return (AS_OF - date.fromisoformat(s)).days if s else None


def facts(c: dict) -> dict:
    p, rel = c["profile"], c.get("relationships") or {}
    years = sorted((c.get("financials") or {}).get("years") or [], key=lambda y: y["financialYear"])
    cases = (c.get("litigation") or {}).get("cases") or []
    flags: list[dict] = []
    flag = lambda sev, code, text: flags.append({"severity": sev, "code": code, "text": text})

    # --- Profile
    if p["status"] != "Active":
        flag("high", "status", f"Company status is '{p['status']}'")
    former = [f.get("name", str(f)) if isinstance(f, dict) else str(f) for f in p.get("formerNames") or []]
    if former:
        flag("info", "former_names", "Formerly known as " + ", ".join(former))

    # --- Ownership and board
    directors = rel.get("directors") or []
    holders = sorted(rel.get("shareholders") or [], key=lambda s: -(s.get("percentage") or 0))
    appointed = {d["name"]: d.get("appointedOn") for d in directors}
    top = holders[0] if holders else None
    recent = [d for d in directors if (days_ago(d.get("appointedOn")) or 9999) <= 365]
    if top and top["percentage"] >= 50 and (days_ago(appointed.get(top["name"])) or 9999) <= 365:
        flag("medium", "control_change", f"Majority shareholder {top['name']} ({top['percentage']}%) "
             f"joined the board on {appointed[top['name']]}, a possible recent change of control")
    elif len(recent) >= 2:
        flag("info", "board_changes", f"{len(recent)} directors appointed in the last 12 months")
    corporate = [s for s in holders if s.get("type") == "company"]
    if corporate:
        flag("info", "corporate_shareholder", "Corporate shareholder(s): " +
             ", ".join(f"{s['name']} ({s['percentage']}%)" for s in corporate))

    # --- Financials
    fin = None
    if not years:
        flag("medium", "no_financials", "No financial statements on record")
    else:
        last = years[-1]
        s, r = last["statements"], last["ratiosAndMetrics"]
        cap, liq = r["capitalStructure"], r["liquidityAndCashFlow"]
        fin = {"latestYear": last["financialYear"], "yearsAvailable": [y["financialYear"] for y in years],
               "revenue": s["revenue"], "profitAfterTax": s["profitAfterTax"],
               "netProfitMargin": r["profitability"]["netProfitMargin"], "totalEquity": s["totalEquity"],
               "borrowings": s["borrowings"], "operatingCashFlow": s["operatingCashFlow"],
               "freeCashFlow": liq["freeCashFlow"], "quickRatio": liq["quickRatio"],
               "leverageRatio": cap["leverageRatio"], "interestCoverageRatio": cap["interestCoverageRatio"],
               "debtServiceCoverageRatio": cap["debtServiceCoverageRatio"],
               "history": [{"year": y["financialYear"], "revenue": y["statements"]["revenue"],
                            "profitAfterTax": y["statements"]["profitAfterTax"],
                            "auditOpinion": y["audit"]["opinion"]} for y in years]}
        if len(years) < 3:
            flag("info", "short_history", f"Only {len(years)} year(s) of financials")
        for y in years:
            if y["audit"]["opinion"] != "Unqualified":
                flag("high", "audit", f"FY{y['financialYear']} audit opinion: {y['audit']['opinion']}")
        if s["totalEquity"] < 0:
            flag("high", "negative_equity", f"Negative equity of {rm(s['totalEquity'])} in FY{last['financialYear']}")
        if s["profitAfterTax"] < 0:
            streak = 0
            for y in reversed(years):
                if y["statements"]["profitAfterTax"] >= 0:
                    break
                streak += 1
            flag("medium", "loss", f"Net loss of {rm(s['profitAfterTax'])} in FY{last['financialYear']}"
                 + (f", {streak} consecutive loss-making years" if streak > 1 else ""))
        if len(years) >= 2:
            prev = years[-2]["statements"]["revenue"]
            growth = s["revenue"] / prev - 1 if prev else None
            fin["revenueGrowth"] = growth
            if growth is not None and growth <= -0.2:
                flag("medium", "revenue_decline", f"Revenue fell {abs(growth):.0%} to {rm(s['revenue'])} in FY{last['financialYear']}")
        if s["operatingCashFlow"] < 0:
            flag("medium", "negative_cash_flow", f"Negative operating cash flow of {rm(s['operatingCashFlow'])}")
        icr = cap["interestCoverageRatio"]
        if icr is not None and icr < 1.5:
            flag("medium", "interest_cover", f"Interest coverage of {icr:.2f}x (below 1.5x)")
        if cap["leverageRatio"] is not None and cap["leverageRatio"] > 2:
            flag("medium", "leverage", f"High leverage: liabilities are {cap['leverageRatio']:.2f}x equity")

    # --- Litigation (being sued matters more than suing)
    against = [k for k in cases if k["role"] == "defendant"]
    for k in against:
        if k["caseType"] == "Winding-up petition" and k["status"] not in ("Withdrawn", "Dismissed"):
            flag("high", "winding_up_petition", f"Winding-up petition against the company ({k['status']}, filed {k['filedOn']})")
    judged = [k for k in against if k["status"] == "Judgment entered"]
    if judged:
        flag("high", "judgment_against", f"{len(judged)} judgment(s) entered against the company, "
             f"totalling {rm(sum(k['claimAmount'] or 0 for k in judged))}")
    pending = [k for k in against if k["status"] == "Pending"]
    if pending:
        flag("medium", "pending_lawsuits", f"{len(pending)} pending case(s) against the company, "
             f"claims totalling {rm(sum(k['claimAmount'] or 0 for k in pending))}")

    flags.sort(key=lambda f: SEVERITY[f["severity"]])
    return {
        "registrationNumber": c["registrationNumber"], "companyName": p["companyName"],
        "status": p["status"], "industry": p["industry"], "state": p["state"],
        "natureOfBusiness": p["natureOfBusiness"], "incorporationDate": p["incorporationDate"],
        "ageYears": days_ago(p["incorporationDate"]) // 365, "shareCapital": p.get("shareCapital"),
        "directors": len(directors),
        "topShareholder": {"name": top["name"], "percentage": top["percentage"]} if top else None,
        "financials": fin,
        "litigation": {"total": len(cases), "asDefendant": len(against), "asPlaintiff": len(cases) - len(against)},
        "flags": flags,
    }


if __name__ == "__main__":
    import collections
    out = [facts(json.loads(l)) for l in open("data/companies.jsonl")]
    with open("outputs/facts.jsonl", "w") as f:
        for x in out:
            f.write(json.dumps(x) + "\n")
    codes = collections.Counter(fl["code"] for x in out for fl in x["flags"])
    sev = collections.Counter(min((fl["severity"] for fl in x["flags"]), key=SEVERITY.get, default="none") for x in out)
    print("wrote outputs/facts.jsonl for", len(out), "companies")
    print("flags by code:", dict(codes.most_common()))
    print("companies by worst severity:", dict(sev))
