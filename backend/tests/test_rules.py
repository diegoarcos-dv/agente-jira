from app.catalog import FakeAssigneeCatalog
from app.rules import collect_review_requirements, decide, infer_work_type


def test_catalog_resolves_alias_and_rejects_combined_names():
    catalog = FakeAssigneeCatalog()
    assert catalog.resolve("Raul Gallardo")["resolution"] == "RESOLVED"
    assert catalog.resolve("Wilfrido / José")["resolution"] == "NOT_FOUND"
    assert catalog.get_by_account_id("local-account-wilfrido")["display_name"] == "Wilfrido Hernández"
    assert len(catalog.list_users()) >= 5


def test_work_type_rules_are_deterministic():
    assert infer_work_type("Error de CORS al consultar el servicio")[0] == "Bug"
    assert infer_work_type("Como usuario quiero consultar mis solicitudes")[0] == "Story"
    assert infer_work_type("Implementar filtros en la tabla")[0] == "Task"


def test_completed_activity_is_excluded_even_with_resolved_assignee():
    decision, reason, _ = decide(
        {"estado_actual": "Completada"},
        {"resolution": "RESOLVED"},
        "Bug",
        0.96,
    )
    assert decision == "EXCLUIR"
    assert "completada" in reason


def test_unknown_assignee_requires_review():
    decision, _, _ = decide(
        {"estado_actual": "Pendiente"},
        {"resolution": "NOT_FOUND"},
        "Task",
        0.88,
    )
    assert decision == "REVISAR"


def test_review_collects_every_actionable_requirement():
    requirements = collect_review_requirements(
        {"estado_actual": "Por confirmar"},
        {"resolution": "NOT_FOUND"},
        "Epic",
        0.78,
    )

    assert [requirement["code"] for requirement in requirements] == [
        "ASSIGNEE_UNRESOLVED",
        "SOURCE_STATE_UNCONFIRMED",
        "WORK_TYPE_UNCONFIRMED",
    ]


def test_confirmed_fields_remove_their_review_requirements():
    requirements = collect_review_requirements(
        {"estado_actual": "Por confirmar"},
        {"resolution": "RESOLVED"},
        "Epic",
        0.78,
        confirmed_fields={"source_state", "work_type"},
    )

    assert requirements == []


def test_reactivated_source_requires_explicit_review_before_inclusion():
    decision, _, _ = decide(
        {"estado_actual": "Completada"},
        {"resolution": "RESOLVED"},
        "Task",
        0.88,
        source_state_overridden=True,
        reactivation_reviewed=False,
    )
    requirements = collect_review_requirements(
        {"estado_actual": "Completada"},
        {"resolution": "RESOLVED"},
        "Task",
        0.88,
        source_state_overridden=True,
        reactivation_reviewed=False,
    )
    assert decision == "REVISAR"
    assert [entry["code"] for entry in requirements] == [
        "REACTIVATION_REVIEW_REQUIRED"
    ]

    confirmed, _, _ = decide(
        {"estado_actual": "Completada"},
        {"resolution": "RESOLVED"},
        "Task",
        0.88,
        source_state_overridden=True,
        reactivation_reviewed=True,
    )
    assert confirmed == "INCLUIR"
