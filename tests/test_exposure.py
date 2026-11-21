"""Fund exposure: parsing an FT holdings page (a synthetic one) and weighting breakdowns by what's held (made-up)."""
from core.exposure import compute
from investments.exposure import parse

PAGE = """
<h2>Asset allocation</h2>
<table><tr><th>Type</th><th>% Net assets</th><th>% Short</th><th>% Long</th></tr>
<tr><td>Non-UK stock</td><td>70.00%</td><td>0.00%</td><td>70.00%</td></tr>
<tr><td>UK stock</td><td>10.00%</td><td>0.00%</td><td>10.00%</td></tr>
<tr><td>Non-UK bond</td><td>25.00%</td><td>0.00%</td><td>25.00%</td></tr>
<tr><td>Cash</td><td>-5.00%</td><td>5.00%</td><td>0.00%</td></tr></table>
<table><tr><th>Sector</th><th>% Net assets</th><th>Category average</th></tr>
<tr><td>Technology</td><td>30.00%</td><td>28.00%</td></tr></table>
<table><tr><th>Sector</th><th>% Net assets</th><th>Category average</th></tr>
<tr class="row--colored"><td>Americas</td><td>50.00%</td><td>60.00%</td></tr>
<tr><td>United States</td><td>48.00%</td><td>58.00%</td></tr><tr><td>Canada</td><td>2.00%</td><td>2.00%</td></tr>
<tr class="row--colored"><td>Greater Europe</td><td>20.00%</td><td>20.00%</td></tr>
<tr><td>United Kingdom</td><td>10.00%</td><td>8.00%</td></tr><tr><td>Eurozone</td><td>10.00%</td><td>12.00%</td></tr>
<tr class="row--colored"><td>Greater Asia</td><td>10.00%</td><td>10.00%</td></tr>
<tr><td>Japan</td><td>10.00%</td><td>6.00%</td></tr></table>
<table><tr><th>Company</th><th>1 year change</th></tr><tr><td>Some Co</td><td>+1.00%</td></tr></table>
"""


def run():
    b = parse(PAGE)
    assert b["asset"] == {"Non-UK stock": 70.0, "UK stock": 10.0, "Non-UK bond": 25.0, "Cash": -5.0}
    assert b["regions"] == {"Americas": {"United States": 48.0, "Canada": 2.0},
                            "Greater Europe": {"United Kingdom": 10.0, "Eurozone": 10.0}, "Greater Asia": {"Japan": 10.0}}
    assert b["sectors"] == {"Technology": 30.0}

    sources = [{"data": {"accounts": [
        {"name": "ISA", "type": "isa", "cash": 100.0, "total": 1100.0,
         "holdings": [{"id": "gb00b0000001", "value": 800.0}, {"id": "unknown-fund", "value": 200.0}]},
        {"name": "Saver", "type": "savings", "cash": 500.0, "total": 500.0},
        {"name": "Current", "type": "current", "cash": 900.0, "total": 900.0, "in_total": False}]}}]
    ex = compute(sources, {"gb00b0000001": {**b, "fetched": "2026-11-21"}})
    asset = {x["name"]: x["value"] for x in ex["asset"]}
    # 800 split 80/25/-5 (of 100): shares 640, bonds 200, cash -40; plus 100 uninvested + 500 savings; 200 unknown
    assert asset == {"Shares": 640.0, "Bonds": 200.0, "Cash": 560.0, "Not analysed": 200.0}, asset
    assert sum(asset.values()) == 1600.0, "everything counted once; the current account (not in total) left out"
    regions = {(r["group"], r["name"]): r["value"] for r in ex["regions"]}
    assert regions[("Americas", "United States")] == 384.0 and regions[("Asia-Pacific", "Japan")] == 80.0
    assert ex["regions"][0]["name"] == "United States", "largest first"
    assert ex["funds"] == 2 and ex["analysed"] == 1 and ex["as_of"] == "2026-11-21"
    print("exposure OK")


if __name__ == "__main__":
    run()
