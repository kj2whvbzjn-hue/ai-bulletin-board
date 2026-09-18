from pathlib import Path

html = Path("pages/index.html").read_text(encoding="utf-8")

# At <=520px, keep all five summary metrics visible but in one compact row.
# The accepted 390x844 baseline placed the first task target 147px below the
# initial viewport; collapsing the previous 2-column/3-row summary is the
# narrowly-scoped density change intended to recover that vertical space.
required = [
    "@media(max-width:520px)",
    ".summary{grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;margin:10px 0}",
    ".metric{padding:8px 4px;text-align:center}",
    ".metric strong{font-size:1.15rem}",
    ".metric span{font-size:.58rem;letter-spacing:0}",
]
for snippet in required:
    assert snippet in html, f"missing narrow summary density contract: {snippet}"

# Preserve the five summary values and the mobile-card task surface.
for metric_id in ["m-open", "m-claimed", "m-review", "m-completed", "m-risk"]:
    assert f'id="{metric_id}"' in html
assert 'id="cards" class="mobile-cards"' in html
assert "@media(max-width:900px)" in html
assert ".desktop-table{display:none}.mobile-cards{display:grid" in html

print("PAGES_NARROW_TASK_VISIBILITY_REGRESSION_OK")
