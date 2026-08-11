from app.sprints import normalize_sprint_catalog, resolve_sprint, revalidate_sprint


def catalog():
    return [
        {"id": "22", "name": "SPT-FUTURO", "state": "future", "board_id": "7"},
        {"id": "11", "name": "SPT-ACTIVO", "state": "active", "board_id": "7"},
    ]


def test_plan_name_is_resolved_and_user_never_needs_the_id():
    result = resolve_sprint("spt-activo", catalog())

    assert result["mode"] == "PLAN_NAME_MATCH"
    assert result["selected"]["id"] == "11"
    assert result["error"] is None


def test_blank_value_auto_selects_only_one_active_sprint():
    result = resolve_sprint(None, catalog())

    assert result["mode"] == "AUTO_SINGLE_ACTIVE"
    assert result["selected"]["id"] == "11"
    assert result["warning"]["code"] == "SPRINT_AUTO_SELECTED"


def test_multiple_active_sprints_never_choose_silently():
    result = resolve_sprint(
        None,
        catalog() + [{"id": "33", "name": "SPT-OTRO", "state": "active"}],
    )

    assert result["selected"] is None
    assert result["error"]["code"] == "SPRINT_SELECTION_REQUIRED"


def test_closed_sprints_are_removed_and_fail_revalidation():
    normalized = normalize_sprint_catalog(
        catalog() + [{"id": "44", "name": "SPT-CERRADO", "state": "closed"}]
    )

    assert {sprint["id"] for sprint in normalized} == {"11", "22"}
    assert revalidate_sprint("44", normalized) is None
