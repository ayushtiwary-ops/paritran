"""Engine linkage tests (SPEC 6.3, 6.1). Plain python, no db.

The seed-42 metrics are compared against the committed results.json,
the exactness oracle produced by src/paritran_prototype.py.
"""

import json
from pathlib import Path

from paritran.engine import linkage, synthetic

SEED = 42
RESULTS_JSON = Path(__file__).resolve().parents[2] / "results.json"


def _oracle() -> dict:
    return json.loads(RESULTS_JSON.read_text())


def test_seed42_metrics_match_results_json_exactly():
    oracle = _oracle()
    result = linkage.link(synthetic.generate(SEED))
    m = result.metrics
    assert m.n_complaints == oracle["n_complaints"] == 297
    assert m.networks_found == oracle["networks_found"] == 6
    assert m.precision == oracle["linkage_precision"] == 0.957
    assert m.recall == oracle["linkage_recall"] == 0.966
    assert m.f1 == oracle["linkage_f1"] == 0.962


def test_communities_are_min_size_networks():
    result = linkage.link(synthetic.generate(SEED))
    assert all(len(com) >= 5 for com in result.communities)
    assert result.metrics.networks_found == len(result.communities)
    # Communities are disjoint sets of complaint ids.
    seen: set[int] = set()
    for com in result.communities:
        assert not (com & seen)
        seen |= com


def test_pred_covers_every_complaint():
    bundle = synthetic.generate(SEED)
    result = linkage.link(bundle)
    assert set(result.pred) == {c.id for c in bundle.complaints}
    # Noise complaints share no identifiers, so no two of them may land
    # in the same predicted community.
    noise_labels = [result.pred[c.id] for c in bundle.complaints
                    if c.synd < 0]
    assert len(noise_labels) == len(set(noise_labels))


def test_metrics_independent_of_narratives():
    with_text = linkage.link(synthetic.generate(SEED, narratives=True))
    without_text = linkage.link(synthetic.generate(SEED, narratives=False))
    assert with_text.metrics == without_text.metrics
    assert with_text.pred == without_text.pred


def test_seed_sensitivity_not_canned():
    """A non-42 seed must move the metrics: nothing here is hardcoded."""
    m = linkage.link(synthetic.generate(43, narratives=False)).metrics
    assert m.n_complaints != 297
    assert (m.precision, m.recall, m.f1) != (0.957, 0.966, 0.962)
    assert 0.0 <= m.precision <= 1.0
    assert 0.0 <= m.recall <= 1.0
    assert 0.0 <= m.f1 <= 1.0
