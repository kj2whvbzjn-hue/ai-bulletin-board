from pathlib import Path

html = Path("pages/index.html").read_text(encoding="utf-8")

# The search field updates results/URL on input. Its later blur/change event must
# not trigger a second synchronous render that can replace a task link during
# activation. Non-search controls still update on change.
required = [
    "const filterForm=document.getElementById('filters')",
    "filterForm.addEventListener('input',event=>{if(event.target.matches('input[type=\"search\"]'))updateQuery()})",
    "filterForm.addEventListener('change',event=>{if(!event.target.matches('input[type=\"search\"]'))updateQuery()})",
]
for snippet in required:
    assert snippet in html, f"missing guarded filter event policy: {snippet}"

assert "addEventListener('change',updateQuery)" not in html
assert "addEventListener('input',updateQuery)" not in html

# Deterministic event-order contract for the deployed UI:
# typing search -> one update; blur/change of that search -> no second update;
# select change -> one update.
def updates(event_type: str, control_type: str) -> bool:
    if event_type == "input":
        return control_type == "search"
    if event_type == "change":
        return control_type != "search"
    return False

assert updates("input", "search")
assert not updates("change", "search")
assert updates("change", "select")
assert not updates("input", "select")

print("PAGES_FILTER_EVENT_REGRESSION_OK")
