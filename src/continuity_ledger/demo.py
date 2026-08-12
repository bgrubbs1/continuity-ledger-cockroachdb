"""Fixed synthetic scenarios for the public, no-login contest demo."""

from __future__ import annotations

from dataclasses import dataclass

from .agent import AgentOutcome, ContinuityAgent
from .models import LedgerEvent
from .service import ContinuityService


DEMO_TENANT = "demo_tenant"
DEMO_TIMESTAMP = "2026-08-11T00:00:00+00:00"


@dataclass(frozen=True, slots=True)
class DemoScenario:
    scenario_id: str
    title: str
    prior_incident_id: str
    prior_summary: str
    observation: str
    expected_action: str
    run_incident_id: str


SCENARIOS = {
    scenario.scenario_id: scenario
    for scenario in (
        DemoScenario(
            scenario_id="ingest_backlog",
            title="Ingest backlog",
            prior_incident_id="prior_ingest",
            prior_summary="Synthetic ingest checksum retries coincided with a delayed package",
            observation="Synthetic ingest checksum delay",
            expected_action="inspect_ingest_validation",
            run_incident_id="run_ingest",
        ),
        DemoScenario(
            scenario_id="transcode_saturation",
            title="Transcode saturation",
            prior_incident_id="prior_transcode",
            prior_summary="Synthetic transcode workers reached capacity during a queue delay",
            observation="Synthetic transcode worker delay",
            expected_action="inspect_transcode_capacity",
            run_incident_id="run_transcode",
        ),
        DemoScenario(
            scenario_id="review_status",
            title="Review status uncertainty",
            prior_incident_id="prior_review",
            prior_summary="Synthetic review memory required a fresh publish status check",
            observation="Synthetic review publish status uncertainty",
            expected_action="verify_publish_status",
            run_incident_id="run_review",
        ),
    )
}


def scenario_catalog() -> list[dict[str, str]]:
    return [
        {
            "id": scenario.scenario_id,
            "title": scenario.title,
            "observation": scenario.observation,
            "expected_action": scenario.expected_action,
        }
        for scenario in SCENARIOS.values()
    ]


def seed_demo_memory(service: ContinuityService) -> dict[str, int]:
    inserted = 0
    for index, scenario in enumerate(SCENARIOS.values(), start=1):
        event = LedgerEvent(
            tenant_id=DEMO_TENANT,
            incident_id=scenario.prior_incident_id,
            sequence=1,
            kind="handoff",
            summary=scenario.prior_summary,
            evidence={"source": "fictional contest fixture", "state": "reviewed"},
            idempotency_key=f"demo_seed_{index}",
            created_at=DEMO_TIMESTAMP,
        )
        inserted += int(service.record(event))
    return {"inserted": inserted, "available": len(SCENARIOS)}


def run_demo_scenario(
    service: ContinuityService,
    scenario_id: str,
) -> AgentOutcome | None:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError("unknown demo scenario")
    prior = service.recall(DEMO_TENANT, scenario.prior_summary, 20)
    if not any(item.event.incident_id == scenario.prior_incident_id for item in prior):
        return None
    outcome = ContinuityAgent(service).run(
        tenant_id=DEMO_TENANT,
        incident_id=scenario.run_incident_id,
        sequence=10,
        observation=scenario.observation,
        idempotency_key=f"demo_run_{scenario.scenario_id}",
        created_at=DEMO_TIMESTAMP,
    )
    if outcome.action != scenario.expected_action:
        raise RuntimeError("demo action did not match the fixed evidence contract")
    return outcome


DEMO_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Continuity Ledger</title><style>
:root{color-scheme:dark;--bg:#07111f;--panel:#101d2e;--line:#28415f;--accent:#7de3c1;--text:#e8f0f8;--muted:#9eb0c5}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,sans-serif;background:radial-gradient(circle at top,#17304a,var(--bg) 55%);color:var(--text)}
main{max-width:900px;margin:auto;padding:48px 20px}h1{font-size:clamp(2.2rem,6vw,4.6rem);line-height:1;margin:.2em 0}.eyebrow{color:var(--accent);letter-spacing:.16em;text-transform:uppercase;font-weight:700}.lede{max-width:700px;color:var(--muted);font-size:1.15rem}
.flow{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:32px 0}.step,.result{border:1px solid var(--line);background:rgba(16,29,46,.92);border-radius:16px;padding:20px}.step b{color:var(--accent)}button{border:0;border-radius:999px;background:var(--accent);color:#062018;padding:12px 18px;font-weight:800;cursor:pointer;margin:6px 6px 6px 0}button.secondary{background:#29445f;color:var(--text)}pre{white-space:pre-wrap;min-height:160px;color:#cde9df}.note{font-size:.9rem;color:var(--muted)}
@media(max-width:700px){.flow{grid-template-columns:1fr}}
</style></head><body><main>
<p class="eyebrow">CockroachDB × AWS agentic memory demo</p><h1>Continuity Ledger</h1>
<p class="lede">A synthetic incident-handoff agent that retrieves tenant-scoped CockroachDB vector memory, chooses a reversible action, cites its evidence, and appends the decision.</p>
<section class="flow"><div class="step"><b>1 · Store</b><p>Seed three fictional prior handoffs in CockroachDB.</p></div><div class="step"><b>2 · Retrieve</b><p>Vector search recalls only the demo tenant's relevant memory.</p></div><div class="step"><b>3 · Act</b><p>The policy chooses a bounded action and stores its cited decision.</p></div></section>
<button id="seed">Seed durable memory</button><button class="secondary" data-case="ingest_backlog">Run ingest case</button><button class="secondary" data-case="transcode_saturation">Run transcode case</button><button class="secondary" data-case="review_status">Run review case</button>
<div class="result"><strong>Evidence receipt</strong><pre id="output">Seed memory, then run a case.</pre></div>
<p class="note">Fixed fictional scenarios only. No personal, employer, customer, household, credential, or private-network data is accepted. The policy is deterministic and is not represented as an LLM.</p>
</main><script>
const out=document.querySelector('#output');async function call(path,body={}){out.textContent='Working…';const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const j=await r.json();out.textContent=JSON.stringify(j,null,2)}
document.querySelector('#seed').onclick=()=>call('/demo/seed');document.querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>call('/demo/run',{scenario_id:b.dataset.case}));
</script></body></html>"""
