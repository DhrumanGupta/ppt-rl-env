from server.task_registry import DEFAULT_TASK_REGISTRY, DEFAULT_THEME


def test_default_registry_injects_default_theme_and_difficulty() -> None:
    scenario = DEFAULT_TASK_REGISTRY.get("lattice_health_easy")

    assert scenario.difficulty == "easy"
    assert scenario.theme == DEFAULT_THEME


def test_default_registry_loads_richer_source_pack_structure() -> None:
    scenario = DEFAULT_TASK_REGISTRY.get("northstar_growth_medium")

    assert scenario.source_pack.brief is not None
    assert len(scenario.source_pack.documents) == 3
    assert scenario.source_pack.documents[0].pages
