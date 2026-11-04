"""FUT-020: optional vector retrieval beside FTS5/BM25, offline."""
import asyncio
import hashlib
import importlib

import pytest
from fastapi.testclient import TestClient

from src.config import get_research_config
from src.embeddings import (
    EmbeddingError, LocalHashEmbedder, ModelEndpointEmbedder, cosine, create_embedding_provider,
)
from src.local_store import LocalStateStore
from src.retrieval_eval import compare_retrieval_modes, precision_recall_rr
from src.services import EvidenceService

T, P, R = "tenant", "project", "run"

PASSAGES = {
    "E-GRAPH": "Graphene electrodes improve battery charging speed and energy density.",
    "E-SOLAR": "Perovskite solar cells reach high conversion efficiency under sunlight.",
    "E-BIRD": "Migratory birds navigate using the earth magnetic field.",
}


@pytest.fixture(autouse=True)
def fresh_config():
    get_research_config.cache_clear()
    yield
    get_research_config.cache_clear()


def evidence(evidence_id, passage, tenant=T, run=R, decision="allowed", eligibility="eligible"):
    return dict(
        tenant_id=tenant, project_id=P, run_id=run, report_revision=1, evidence_id=evidence_id,
        source_id=f"SRC-{evidence_id}", source_type="paper", title=f"Study {evidence_id}",
        url=f"https://example.org/{evidence_id}", retrieved_at="2026-01-01T00:00:00",
        peer_review_status="peer-reviewed", passage=passage,
        content_hash="sha256:" + hashlib.sha256(passage.encode()).hexdigest(),
        source_use_decision=decision, eligibility_status=eligibility, policy_version="t",
        authors=[], independence_group_ids=[evidence_id], independence_status="assessed")


def make_service(tmp_path, embedder="local", passages=PASSAGES):
    store = LocalStateStore(str(tmp_path / "v.db"))
    for evidence_id, passage in passages.items():
        store.put("evidence", T, P, evidence_id, evidence(evidence_id, passage))
    embedder = LocalHashEmbedder() if embedder == "local" else embedder
    return store, EvidenceService(store, embedder=embedder)


def run(coro):
    return asyncio.run(coro)


def ids(results):
    return [r.evidence_id for r in results]


class FailingEmbedder(LocalHashEmbedder):
    """Succeeds for `ok_calls` embed calls, then fails like an unavailable provider."""

    def __init__(self, ok_calls=0, batch_size=1):
        super().__init__()
        self.ok_calls, self.calls, self.batch_size = ok_calls, 0, batch_size

    def embed(self, texts):
        self.calls += 1
        if self.calls > self.ok_calls:
            raise EmbeddingError("provider down")
        return super().embed(texts)


# ------------------------------------------------------------------ defaults preserved

def test_default_mode_is_keyword_and_matches_fts_results(tmp_path):
    store, service = make_service(tmp_path)
    out = run(service.search_evidence_detailed(T, P, R, "graphene battery"))
    assert out["mode"] == "keyword" and out["requested_mode"] == "keyword"
    assert out["degraded_reason"] is None
    assert ids(out["results"]) == ["E-GRAPH"]
    assert ids(run(service.search_evidence(T, P, R, "graphene battery"))) == ["E-GRAPH"]


def test_unknown_search_type_is_rejected(tmp_path):
    _, service = make_service(tmp_path)
    with pytest.raises(ValueError):
        run(service.search_evidence_detailed(T, P, R, "x", "bogus"))


# ------------------------------------------------------------------ vectors

def test_semantic_and_hybrid_use_indexed_vectors(tmp_path):
    store, service = make_service(tmp_path)
    assert run(service.index_vectors(T, P, R))["indexed"] == 3
    semantic = run(service.search_evidence_detailed(T, P, R, "battery charging graphene", "semantic"))
    hybrid = run(service.search_evidence_detailed(T, P, R, "battery charging graphene", "hybrid"))
    assert semantic["mode"] == "semantic" and ids(semantic["results"])[0] == "E-GRAPH"
    assert hybrid["mode"] == "hybrid" and ids(hybrid["results"])[0] == "E-GRAPH"
    assert hybrid["degraded_reason"] is None


@pytest.mark.parametrize("embedder,reason", [(None, "embeddings_disabled"),
                                              ("local", "no_vectors_indexed")])
def test_missing_embeddings_degrade_to_keyword_with_reason(tmp_path, embedder, reason):
    _, service = make_service(tmp_path, embedder=embedder)
    out = run(service.search_evidence_detailed(T, P, R, "graphene battery", "hybrid"))
    assert out["mode"] == "keyword" and out["degraded_reason"] == reason
    assert ids(out["results"]) == ["E-GRAPH"]  # keyword results still served


def test_index_is_idempotent_and_requires_a_provider(tmp_path):
    store, service = make_service(tmp_path)
    run(service.index_vectors(T, P, R))
    again = run(service.index_vectors(T, P, R))
    assert again["indexed"] == 0 and again["already_current"] == 3
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM evidence_vectors").fetchone()[0] == 3
    _, disabled = make_service(tmp_path / "x" if False else tmp_path, embedder=None)
    with pytest.raises(ValueError):
        run(disabled.index_vectors(T, P, R))


def test_stale_vectors_are_excluded_until_reindexed(tmp_path):
    store, service = make_service(tmp_path)
    run(service.index_vectors(T, P, R))
    changed = "Graphene supercapacitors store charge very differently now."
    store.put("evidence", T, P, "E-GRAPH", evidence("E-GRAPH", changed))

    # The stale vector is never scored; with nothing else matching, the search
    # degrades to keyword, which reads the current text.
    out = run(service.search_evidence_detailed(T, P, R, "graphene supercapacitors charge", "semantic"))
    assert out["stale_vectors"] == 1
    assert out["mode"] == "keyword" and out["degraded_reason"] == "stale_vectors"
    fixed = run(service.index_vectors(T, P, R))
    assert fixed["indexed"] == 1
    out = run(service.search_evidence_detailed(T, P, R, "graphene supercapacitors charge", "semantic"))
    assert out["stale_vectors"] == 0 and out["mode"] == "semantic"
    assert ids(out["results"])[0] == "E-GRAPH"


def test_all_stale_vectors_report_stale_and_fall_back(tmp_path):
    store, service = make_service(tmp_path, passages={"E-GRAPH": PASSAGES["E-GRAPH"]})
    run(service.index_vectors(T, P, R))
    store.put("evidence", T, P, "E-GRAPH", evidence("E-GRAPH", PASSAGES["E-GRAPH"] + " Revised."))
    out = run(service.search_evidence_detailed(T, P, R, "graphene battery", "hybrid"))
    assert out["mode"] == "keyword" and out["degraded_reason"] == "stale_vectors"


@pytest.mark.parametrize("change", [dict(decision="blocked"), dict(eligibility="ineligible"),
                                    dict(decision="requires_review")])
def test_revoked_evidence_is_excluded_in_every_mode(tmp_path, change):
    store, service = make_service(tmp_path)
    run(service.index_vectors(T, P, R))
    store.put("evidence", T, P, "E-GRAPH", evidence("E-GRAPH", PASSAGES["E-GRAPH"], **change))
    for mode in ("keyword", "semantic", "hybrid"):
        out = run(service.search_evidence_detailed(T, P, R, "graphene battery charging", mode))
        assert "E-GRAPH" not in ids(out["results"]), mode


def test_other_tenants_vectors_and_ids_never_leak(tmp_path):
    store, service = make_service(tmp_path)
    # Same run and evidence ids under another tenant, with different text.
    store.put("evidence", "other", P, "E-GRAPH",
              evidence("E-GRAPH", "Graphene secret of another tenant battery.", tenant="other"))
    run(service.index_vectors(T, P, R))
    run(service.index_vectors("other", P, R))
    for mode in ("keyword", "semantic", "hybrid"):
        mine = run(service.search_evidence_detailed(T, P, R, "graphene battery", mode))
        theirs = run(service.search_evidence_detailed("other", P, R, "graphene battery", mode))
        assert all(r.tenant_id == T for r in mine["results"])
        assert [r.passage for r in theirs["results"]] == ["Graphene secret of another tenant battery."]


def test_other_runs_are_not_searched(tmp_path):
    store, service = make_service(tmp_path)
    store.put("evidence", T, P, "E-OTHER", evidence("E-OTHER", PASSAGES["E-GRAPH"], run="run-2"))
    run(service.index_vectors(T, P, R))
    run(service.index_vectors(T, P, "run-2"))
    for mode in ("keyword", "semantic", "hybrid"):
        assert "E-OTHER" not in ids(run(service.search_evidence_detailed(
            T, P, R, "graphene battery", mode))["results"])


def test_provider_outage_at_query_time_falls_back_to_keyword(tmp_path):
    store, service = make_service(tmp_path)
    run(service.index_vectors(T, P, R))
    service.embedder = FailingEmbedder(ok_calls=0)  # same model_id, now unavailable
    out = run(service.search_evidence_detailed(T, P, R, "graphene battery", "hybrid"))
    assert out["mode"] == "keyword" and out["degraded_reason"] == "embedding_provider_error"
    assert ids(out["results"]) == ["E-GRAPH"]


def test_interrupted_indexing_keeps_progress_and_resumes_without_duplicates(tmp_path):
    store, service = make_service(tmp_path, embedder=FailingEmbedder(ok_calls=2))
    with pytest.raises(EmbeddingError):
        run(service.index_vectors(T, P, R))
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM evidence_vectors").fetchone()[0] == 2

    service.embedder = LocalHashEmbedder()
    resumed = run(service.index_vectors(T, P, R))
    assert resumed["indexed"] == 1 and resumed["already_current"] == 2
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM evidence_vectors").fetchone()[0] == 3


def test_vectors_from_another_model_are_ignored_and_rebuild_replaces(tmp_path):
    store, service = make_service(tmp_path)
    run(service.index_vectors(T, P, R))

    class Other(LocalHashEmbedder):
        model_id = "local-hash-v2"

    service.embedder = Other()
    out = run(service.search_evidence_detailed(T, P, R, "graphene battery", "semantic"))
    assert out["degraded_reason"] == "no_vectors_indexed"
    run(service.index_vectors(T, P, R, rebuild=True))
    out = run(service.search_evidence_detailed(T, P, R, "graphene battery", "semantic"))
    assert out["mode"] == "semantic"


# ------------------------------------------------------------------ providers

class FakeEmbeddingsClient:
    def __init__(self, dimensions=4, fail=False, short=False):
        self.dimensions, self.fail, self.short, self.batches = dimensions, fail, short, []
        self.embeddings = self

    def create(self, model, input, dimensions):
        self.batches.append(list(input))
        if self.fail:
            raise RuntimeError("secret-endpoint-detail 401")
        data = [type("D", (), {"index": i, "embedding": [float(i + 1)] * self.dimensions})()
                for i in reversed(range(len(input)))]  # returned out of order
        return type("R", (), {"data": data[:-1] if self.short else data})()


def test_model_endpoint_embedder_batches_orders_and_validates():
    client = FakeEmbeddingsClient()
    embedder = ModelEndpointEmbedder(client, "emb", dimensions=4, batch_size=2)
    vectors = embedder.embed(["a", "b", "c"])
    assert [len(b) for b in client.batches] == [2, 1]
    assert vectors[0] == [1.0] * 4 and vectors[1] == [2.0] * 4  # restored to input order
    assert embedder.model_id == "endpoint:emb"
    with pytest.raises(EmbeddingError, match="size"):
        ModelEndpointEmbedder(FakeEmbeddingsClient(short=True), "emb", 4).embed(["a", "b"])
    with pytest.raises(EmbeddingError, match="dimensions"):
        ModelEndpointEmbedder(FakeEmbeddingsClient(dimensions=3), "emb", 4).embed(["a"])


def test_provider_errors_do_not_leak_internals():
    with pytest.raises(EmbeddingError) as error:
        ModelEndpointEmbedder(FakeEmbeddingsClient(fail=True), "emb", 4).embed(["a"])
    assert "secret-endpoint-detail" not in str(error.value)


def test_provider_factory_is_explicit_about_what_it_needs():
    assert create_embedding_provider("none") is None
    assert isinstance(create_embedding_provider("local_hash"), LocalHashEmbedder)
    with pytest.raises(ValueError, match="OpenAI-compatible"):
        create_embedding_provider("model_endpoint")
    with pytest.raises(ValueError):
        create_embedding_provider("nonsense")


def test_local_hash_embedder_is_deterministic_and_normalised():
    embedder = LocalHashEmbedder()
    a, b = embedder.embed(["Graphene  battery", "graphene battery"])
    assert a == b and abs(cosine(a, a) - 1.0) < 1e-9
    assert cosine(a, embedder.embed(["medieval baltic trade"])[0]) < 0.3


# ------------------------------------------------------------------ evaluation harness

def test_metric_arithmetic():
    assert precision_recall_rr(["a", "x", "b"], {"a", "b", "c"}, 3) == (2 / 3, 2 / 3, 1.0)
    assert precision_recall_rr(["x", "y", "a"], {"a"}, 2) == (0.0, 0.0, 0.0)
    assert precision_recall_rr([], {"a"}, 5) == (0.0, 0.0, 0.0)


def test_comparison_reports_without_claiming_a_pass_unless_thresholds_given(tmp_path):
    _, service = make_service(tmp_path)
    run(service.index_vectors(T, P, R))
    cases = [
        {"case_id": "c1", "query": "battery charging graphene", "relevant_evidence_ids": ["E-GRAPH"]},
        {"case_id": "c2", "query": "solar conversion efficiency", "relevant_evidence_ids": ["E-SOLAR"],
         "split": "held_out"},
        # One relevant item shares no terms with the query, so recall is 0.5 here.
        {"case_id": "c3", "query": "graphene battery", "relevant_evidence_ids": ["E-GRAPH", "E-BIRD"]},
    ]
    report = run(compare_retrieval_modes(service, T, P, R, cases, k=3))
    assert set(report["modes"]) == {"keyword", "semantic", "hybrid"}
    assert all(m["passed"] is None for m in report["modes"].values())
    assert report["modes"]["keyword"]["mrr"] == 1.0
    assert set(report["delta_vs_keyword"]) == {"semantic", "hybrid"}
    assert report["modes"]["keyword"]["per_case"][1]["split"] == "held_out"

    keyword = report["modes"]["keyword"]
    assert keyword["precision_at_k"] == 1.0 and abs(keyword["recall_at_k"] - 5 / 6) < 1e-9

    strict = run(compare_retrieval_modes(service, T, P, R, cases, k=3,
                                         thresholds={"precision": 1.0, "recall": 1.0, "mrr": 1.0}))
    assert strict["modes"]["keyword"]["passed"] is False  # mean recall is 5/6
    lenient = run(compare_retrieval_modes(service, T, P, R, cases, k=3,
                                          thresholds={"precision": 0.9, "recall": 0.8, "mrr": 1.0}))
    assert lenient["modes"]["keyword"]["passed"] is True


def test_degraded_modes_fail_a_thresholded_comparison(tmp_path):
    _, service = make_service(tmp_path, embedder=None)
    cases = [{"case_id": "c1", "query": "graphene battery", "relevant_evidence_ids": ["E-GRAPH"]}]
    report = run(compare_retrieval_modes(service, T, P, R, cases, k=3, modes=("hybrid",),
                                         thresholds={"precision": 0.0}))
    assert report["modes"]["hybrid"]["degraded_cases"] == 1
    assert report["modes"]["hybrid"]["passed"] is False


# ------------------------------------------------------------------ API

def test_api_search_reports_mode_and_index_endpoint(tmp_path, monkeypatch):
    db = tmp_path / "api.db"
    store = LocalStateStore(str(db))
    store.put("project", T, P, P, {
        "tenant_id": T, "project_id": P, "name": "Test", "data_policy_version": "1",
        "max_budget_usd": 1, "created_at": "2026-09-19T10:00:00", "updated_at": "2026-09-19T10:00:00",
        "members": {"owner": ["researcher", "admin"], "outsider": []}})
    store.put("run", T, P, R, {
        "run_id": R, "state": "collecting", "report_revision": 1, "policy_epoch": 0,
        "configuration_snapshot_id": "cfg", "start_time": "2026-09-19T10:00:00",
        "updated_time": "2026-09-19T10:00:00", "tenant_id": T, "project_id": P,
        "research_request": {"title": "R", "primary_question": "Q?", "scope_description": "S"}})
    for evidence_id, passage in PASSAGES.items():
        store.put("evidence", T, P, evidence_id, evidence(evidence_id, passage))

    monkeypatch.setenv("LOCAL_DB_PATH", str(db))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_PROVIDER", "local_hash")
    from src.config import get_api_config, get_azure_config, get_model_config
    for fn in (get_api_config, get_azure_config, get_model_config, get_research_config):
        fn.cache_clear()
    import src.main as main_module
    main_module = importlib.reload(main_module)
    h = {"X-Tenant-Id": T, "X-User-Id": "owner"}
    base = f"/api/v1/projects/{P}/runs/{R}"

    with TestClient(main_module.app) as client:
        before = client.post(f"{base}/search", headers=h,
                             json={"query": "graphene battery", "search_type": "hybrid"}).json()
        assert before["mode"] == "keyword" and before["degraded_reason"] == "no_vectors_indexed"

        assert client.post(f"{base}/index-vectors", headers={**h, "X-User-Id": "outsider"}).status_code == 403
        indexed = client.post(f"{base}/index-vectors", headers=h)
        assert indexed.status_code == 200 and indexed.json()["indexed"] == 3

        after = client.post(f"{base}/search", headers=h,
                            json={"query": "graphene battery", "search_type": "hybrid"}).json()
        assert after["mode"] == "hybrid" and after["results"][0]["evidence_id"] == "E-GRAPH"
        default = client.post(f"{base}/search", headers=h, json={"query": "graphene battery"}).json()
        assert default["requested_mode"] == "keyword"
        assert client.post(f"{base}/search", headers=h,
                           json={"query": "x", "search_type": "bogus"}).status_code == 422
