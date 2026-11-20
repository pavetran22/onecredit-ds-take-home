"""Profile companies.jsonl: what values exist, what's missing, what looks risky."""
import json, collections
from datetime import date

C = [json.loads(l) for l in open("data/companies.jsonl")]
cnt = lambda xs: dict(collections.Counter(xs).most_common())
print("companies:", len(C))
print("top-level keys:", cnt(k for c in C for k in c))
P = [c.get("profile") or {} for c in C]
print("\nstatus:", cnt(p.get("status") for p in P))
print("type:", cnt(p.get("companyType") for p in P))
print("industry:", cnt(p.get("industry") for p in P))
print("has former names:", sum(bool(p.get("formerNames")) for p in P))

Y = [y for c in C for y in (c.get("financials") or {}).get("years") or []]
print("\nyears per company:", cnt(len((c.get("financials") or {}).get("years") or []) for c in C))
print("financial years:", cnt(y.get("financialYear") for y in Y))
print("audit opinion:", cnt((y.get("audit") or {}).get("opinion") for y in Y))
print("statement keys:", cnt(k for y in Y for k in (y.get("statements") or {})))
nulls = collections.Counter(f"{g}.{k}" for y in Y for g, d in (y.get("ratiosAndMetrics") or {}).items() for k, v in (d or {}).items() if v is None)
print("null ratios:", dict(nulls.most_common(10)))
nullst = collections.Counter(k for y in Y for k, v in (y.get("statements") or {}).items() if v is None)
print("null statement fields:", dict(nullst))

print("\nnegative equity years:", sum(1 for y in Y if ((y.get("statements") or {}).get("totalEquity") or 0) < 0))
print("loss-making years:", sum(1 for y in Y if ((y.get("statements") or {}).get("profitAfterTax") or 0) < 0))
bad = 0
for y in Y:
    s = y.get("statements") or {}
    try:
        if abs(s["totalAssets"] - s["totalLiabilities"] - s["totalEquity"]) > 1: bad += 1
    except (KeyError, TypeError): pass
print("balance sheet doesn't balance (assets != liabilities + equity):", bad)
mism = 0
for y in Y:
    s, r = y.get("statements") or {}, (y.get("ratiosAndMetrics") or {}).get("profitability") or {}
    if s.get("revenue") and r.get("grossProfitMargin") is not None and s.get("grossProfit") is not None:
        if abs(s["grossProfit"] / s["revenue"] - r["grossProfitMargin"]) > 0.01: mism += 1
print("gross margin ratio disagrees with statements:", mism)

L = [k for c in C for k in (c.get("litigation") or {}).get("cases") or []]
print("\ncompanies with cases:", sum(1 for c in C if (c.get("litigation") or {}).get("cases")), "| total cases:", len(L))
print("case keys:", cnt(k for k in L for k in k))
print("role:", cnt(k.get("role") for k in L))
print("type:", cnt(k.get("type") or k.get("caseType") for k in L))
print("status:", cnt(k.get("status") for k in L))

R = [c.get("relationships") or {} for c in C]
print("\ndirectors per company:", cnt(len(r.get("directors") or []) for r in R))
print("shareholder types:", cnt(s.get("type") for r in R for s in r.get("shareholders") or []))
tot = [round(sum(s.get("percentage") or 0 for s in r.get("shareholders") or []), 1) for r in R]
print("shareholding totals != 100:", [t for t in tot if abs(t - 100) > 0.5])
recent = sum(1 for r in R if any((d.get("appointedOn") or "") >= "2025-07-01" for d in r.get("directors") or []))
print("companies with a director appointed in H2 2025:", recent)
print("\nrecord size (chars): min", min(len(l) for l in open("data/companies.jsonl")), "max", max(len(l) for l in open("data/companies.jsonl")))
