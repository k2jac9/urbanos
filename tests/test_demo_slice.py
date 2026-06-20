"""Guard the committed REAL downtown slice so `make demo` always works on real data."""
from pathlib import Path

from urbanos.risk.agents.supervisor import Supervisor
from urbanos.risk.graph.builder import CivicGraph
from urbanos.risk.ingest.loader import load_into_graph

SLICE = Path(__file__).resolve().parent.parent / "demo_data"


def test_real_slice_loads_in_bbox_with_some_risk():
    g = CivicGraph()
    summary = load_into_graph(g, SLICE)
    assert summary.get("dinesafe", 0) > 0

    addrs = g.addresses(with_coords=True)
    assert addrs, "expected geocoded downtown addresses"
    # Every pin must fall inside the offline PMTiles basemap extent.
    assert all(
        43.62 <= a["lat"] <= 43.69 and -79.43 <= a["lng"] <= -79.34 for a in addrs
    )
    # At least one at-risk address (on EITHER axis) so the map shows a non-green pin.
    sup = Supervisor(g)
    assert any(
        max(sup.score_only(a["label"]).values()) > 0 for a in addrs
    )


def test_no_stringified_null_in_address_labels():
    """Null unit/component fields are sometimes str-joined upstream, leaking a
    literal "None"/"nan" token into single-field source addresses (e.g.
    "630 DANFORTH AVE None M4K 1R3"). Those placeholders must never reach a
    human-facing label, while genuine components (units, street names) survive.
    """
    g = CivicGraph()
    load_into_graph(g, SLICE)
    labels = [a["label"] for a in g.addresses(with_coords=True)]
    assert labels, "expected geocoded downtown addresses"

    placeholders = {"none", "nan", "null", "n/a", "na"}
    offenders = [
        lab
        for lab in labels
        if any(tok.lower() in placeholders for tok in lab.split())
    ]
    assert not offenders, f"placeholder token leaked into labels: {offenders}"

    # The fix must not erase real components: a known unit address keeps its unit.
    denison = [lab for lab in labels if "DENISON" in lab.upper()]
    assert denison and any("Unit-6" in lab for lab in denison), denison


def test_real_cross_dataset_fusion():
    """The slice must show genuine multi-dataset linking across all three sources."""
    g = CivicGraph()
    summary = load_into_graph(g, SLICE)
    assert summary.get("licences", 0) > 0
    assert summary.get("permits", 0) > 0

    triple = [
        a["label"]
        for a in g.addresses(with_coords=True)
        if g.records_for(a["label"], kind="inspection")
        and g.records_for(a["label"], kind="licence")
        and g.records_for(a["label"], kind="permit")
    ]
    assert triple, "expected ≥1 address linking inspection + licence + permit"
