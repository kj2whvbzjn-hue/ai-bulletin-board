from pathlib import Path

html = Path("pages/index.html").read_text(encoding="utf-8")

# At <=520px, keep all five summary metrics visible in one compact row.
# The accepted 390x844 review-needed journey starts 147px below the initial
# viewport; this deterministic source contract recovers vertical space before
# filters/task cards while preserving content and semantics.
required = [
    "@media(max-width:520px)",
    ".summary{grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;margin:10px 0}",
    ".metric{min-width:0;padding:8px 4px;text-align:center}",
    ".metric strong{font-size:1.15rem}",
    ".metric span{font-size:.58rem;line-height:1.15;letter-spacing:0;overflow-wrap:anywhere}",
]
for snippet in required:
    assert snippet in html, f"missing narrow summary density contract: {snippet}"

# Preserve the five summary values and the responsive task-card surface.
for metric_id in ["m-open", "m-claimed", "m-review", "m-completed", "m-risk"]:
    assert f'id="{metric_id}"' in html
assert 'id="cards" class="mobile-cards"' in html
assert "@media(max-width:900px)" in html
assert ".desktop-table{display:none}.mobile-cards{display:grid" in html

# The experiment must not hide, reorder, or rename summary metrics.
labels = ["Open", "Claimed", "Review", "Completed", "Blocked / unsafe"]
positions = [html.index(f"<span>{label}</span>") for label in labels]
assert positions == sorted(positions), "summary metric order changed"

print("PAGES_NARROW_TASK_VISIBILITY_REGRESSION_OK")
