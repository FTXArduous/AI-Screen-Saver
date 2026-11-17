from pathlib import Path
from ..models import CandidateResult

def render_21_9(cycle: int, candidates: list[CandidateResult], star_count: int, out: Path, mode: str, telemetry: dict):
    out.parent.mkdir(parents=True, exist_ok=True)
    ranked = sorted(candidates, key=lambda c: c.total_score, reverse=True)
    rows = "".join(f'<text x="40" y="{250+i*34}" class="row">{c.candidate_id}  |  Base {c.radix:<2} | {c.subdivision:<9} | score {c.total_score:.2f}</text>' for i,c in enumerate(ranked[:8]))
    cards = "".join(f'<rect x="{40+(i%8)*160}" y="{530+(i//8)*74}" width="145" height="56" rx="8" class="candidate"/><text x="{52+(i%8)*160}" y="{552+(i//8)*74}" class="small">{c.candidate_id} · B{c.radix}</text><text x="{52+(i%8)*160}" y="{573+(i//8)*74}" class="tiny">{c.subdivision} · {c.total_score:.2f}</text>' for i,c in enumerate(candidates))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="2100" height="900" viewBox="0 0 2100 900">
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#020916"/><stop offset="1" stop-color="#071d2a"/></linearGradient><linearGradient id="glow"><stop stop-color="#00d9ff"/><stop offset="1" stop-color="#3dff8a"/></linearGradient></defs>
<rect width="2100" height="900" fill="url(#bg)"/><g fill="none" stroke="#0b5263" opacity=".6">{''.join(f'<path d="M {x} 80 V 850"/>' for x in range(0,2100,70))}{''.join(f'<path d="M 0 {y} H 2100"/>' for y in range(80,900,50))}</g>
<text x="40" y="55" class="brand">USHI · GENERATIVE SNAKE</text><text x="1500" y="52" class="status">DEV MODE · CYCLE {cycle:04d} · {mode.upper()}</text>
<rect x="30" y="85" width="1330" height="390" rx="18" class="panel"/><text x="60" y="130" class="heading">MILKY WAY TRAVERSAL · CONCEPTUAL VIEW</text>
<ellipse cx="680" cy="300" rx="500" ry="130" fill="none" stroke="#286f94" stroke-width="2"/><ellipse cx="680" cy="300" rx="380" ry="92" fill="none" stroke="#1b8e87"/><ellipse cx="680" cy="300" rx="240" ry="55" fill="none" stroke="#237eaa"/><circle cx="680" cy="300" r="26" fill="#ffcb79"/><path d="M 170 355 C 260 180 430 410 570 300 S 930 190 1130 315" fill="none" stroke="url(#glow)" stroke-width="6" stroke-linecap="round"/>
{''.join(f'<circle cx="{180+i*38}" cy="{340-65*((i%5)/4)+((i%3)*15)}" r="6" fill="#49ff9a"/>' for i in range(25))}
<text x="60" y="440" class="small">Traversal illustration only · {star_count} input records · not a scientific sky map</text>
<rect x="1390" y="85" width="680" height="390" rx="18" class="panel"/><text x="1425" y="130" class="heading">CYCLE {cycle:04d} · TOP CANDIDATES</text>{rows}
<rect x="30" y="500" width="1320" height="280" rx="18" class="panel"/><text x="60" y="545" class="heading">16 CANDIDATE CONFIGURATIONS</text>{cards}
<rect x="1390" y="500" width="680" height="280" rx="18" class="panel"/><text x="1425" y="545" class="heading">RUNTIME CONNECTIONS</text>
<text x="1425" y="600" class="row">GPU: {telemetry['gpu']}</text><text x="1425" y="642" class="row">HBM: {telemetry['hbm']}</text><text x="1425" y="684" class="row">Cluster migration: {telemetry['cluster']}</text><text x="1425" y="738" class="small">Scores are heuristic until measured benchmarks are connected.</text>
<text x="40" y="850" class="footer">ONE-COMMAND OPERATION · CHECKPOINTED HISTORY · AUTO-ADVANCE IN LOCAL DEV RUNTIME · 21:9 OUTPUT</text>
<style>.brand{{font: bold 34px Arial;fill:#c9f6ff;letter-spacing:3px}}.status{{font:bold 22px Arial;fill:#56ff9b}}.heading{{font:bold 23px Arial;fill:#9beeff}}.row{{font:18px monospace;fill:#d8f7ff}}.small{{font:15px Arial;fill:#8ab8c8}}.tiny{{font:12px Arial;fill:#9bcbd5}}.footer{{font:16px Arial;fill:#5fe8cf;letter-spacing:2px}}.panel{{fill:#061827;stroke:#13718b;stroke-width:2}}.candidate{{fill:#0a2636;stroke:#187f8d;stroke-width:1.5}}</style></svg>'''
    out.write_text(svg, encoding="utf-8")
