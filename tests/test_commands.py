import datetime
from types import SimpleNamespace

import pytest

import taxi.aliases
from taxi.aliases import Mapping
from taxi.plugins import plugins_registry
from taxi_zebra.commands import get_hours_to_be_pushed, get_registered_backend_name


@pytest.fixture
def aliases_database():
    taxi.aliases.aliases_database.reset()
    yield taxi.aliases.aliases_database


def test_get_registered_backend_name_returns_configured_backend_name(monkeypatch):
    backend = object()

    monkeypatch.setattr(plugins_registry, "_backends_registry", {"my_zebra_backend": backend})

    assert get_registered_backend_name(backend) == "my_zebra_backend"


def test_get_hours_to_be_pushed_only_counts_entries_for_selected_backend(aliases_database):
    aliases_database["zebra_alias"] = Mapping(mapping=("1", "1"), backend="my_zebra_backend")
    aliases_database["other_zebra_alias"] = Mapping(mapping=("2", "2"), backend="other_zebra_backend")
    aliases_database["local_alias"] = Mapping(mapping=("3", "3"), backend="local")

    filtered_entries = {
        datetime.date(2026, 4, 1): [
            SimpleNamespace(alias="zebra_alias", hours=2.5),
            SimpleNamespace(alias="other_zebra_alias", hours=1.5),
            SimpleNamespace(alias="local_alias", hours=4),
        ]
    }
    timesheet_collection = SimpleNamespace(entries=SimpleNamespace(filter=lambda **kwargs: filtered_entries))

    assert get_hours_to_be_pushed(timesheet_collection, "my_zebra_backend") == 2.5
