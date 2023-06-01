import datetime
import json
from unittest.mock import patch

import pytest
import responses
import taxi.aliases
from taxi.aliases import Mapping
from taxi.backends import PushEntryFailed
from taxi.projects import ProjectsDb
from taxi.timesheet.entry import Entry
from taxi.ui.tty import TtyUi

from taxi_zebra.backend import Role, ZebraBackend

hostname = "zebralocal"
username = "john.doe"
base_endpoint = "https://{}:443".format(hostname)
urls = {
    name: base_endpoint + url
    for name, url in {
        "login": "/login/user/{}.json".format(username),
        "user_info": "/api/v2/users/me",
        "timesheets": "/api/v2/timesheets/",
        "latestActivityRoles": "/api/v2/latestActivityRoles",
    }.items()
}


@pytest.fixture
def aliases_database():
    taxi.aliases.aliases_database.reset()
    taxi.aliases.aliases_database["alias1"] = Mapping(
        mapping=("1", "1"), backend="local"
    )
    taxi.aliases.aliases_database["alias_do_not_ask_for_role"] = Mapping(
        mapping=("1", "1", "0"), backend="local"
    )

    yield taxi.aliases.aliases_database


@pytest.fixture
def mocked_responses():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as r:
        yield r


@pytest.fixture
def backend(aliases_database, tmp_path):
    projects_db_path = str(tmp_path / "projects.json")
    yield ZebraBackend(
        username=username,
        password="foobar",
        hostname=hostname,
        port=443,
        path="",
        options={},
        context={"view": TtyUi(), "projects_db": ProjectsDb(projects_db_path)},
    )


@pytest.fixture
def authenticated_responses(mocked_responses):
    user_info = {
        "success": True,
        "data": {
            "roles": {
                2: {"id": 2, "parent_id": 1, "full_name": "Role"},
                3: {"id": 3, "parent_id": 1, "full_name": "Role 2"},
            }
        },
    }
    latest_activity_roles = {"success": True, "data": {"1": 2}}

    mocked_responses.add(
        responses.POST,
        urls["login"],
        body="{}",
        status=200,
        content_type="application/json",
    )
    mocked_responses.add(
        responses.GET,
        urls["user_info"],
        body=json.dumps(user_info),
        status=200,
        content_type="application/json",
    )
    mocked_responses.add(
        responses.GET,
        urls["latestActivityRoles"],
        body=json.dumps(latest_activity_roles),
        status=200,
        content_type="application/json",
    )
    mocked_responses.add(
        responses.POST,
        urls["timesheets"],
        body=json.dumps({"success": True}),
        status=200,
        content_type="application/json",
    )

    yield mocked_responses


def require_role(authenticated_responses):
    authenticated_responses.remove(responses.POST, urls["timesheets"])
    authenticated_responses.add(
        responses.POST,
        urls["timesheets"],
        body=json.dumps({"errorCode": "role_needed"}),
        status=400,
        content_type="application/json",
    )
    authenticated_responses.add(
        responses.POST,
        urls["timesheets"],
        body=json.dumps({"success": True}),
        status=200,
        content_type="application/json",
    )

    return authenticated_responses


def test_role_is_prompted_when_needed(authenticated_responses, backend):
    require_role(authenticated_responses)

    role = Role(id="2", parent_id="1", full_name="Role")
    entry = Entry(alias="alias1", duration=1, description="")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        prompt_role.return_value = role
        backend.push_entry(datetime.date.today(), entry)

        prompt_role.assert_called_once_with(
            entry,
            [role, Role(id="3", parent_id="1", full_name="Role 2")],
            {
                "view": backend.context["view"],
                "projects_db": backend.context["projects_db"],
            },
            default_role=Role(id="2", parent_id="1", full_name="Role"),
        )

    push_call = authenticated_responses.calls[-1]
    assert "role_id={}".format(role.id) in push_call.request.body
    assert "individual_action=false" in push_call.request.body


def test_role_is_not_prompted_when_not_needed(authenticated_responses, backend):
    entry = Entry(alias="alias1", duration=1, description="")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        backend.push_entry(datetime.date.today(), entry)
        prompt_role.assert_not_called()


def test_role_is_not_prompted_when_alias_has_role(
    authenticated_responses, backend, aliases_database
):
    entry = Entry(alias="alias2", duration=1, description="")
    aliases_database["alias2"] = Mapping(mapping=("1", "1", "2"), backend="local")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        backend.push_entry(datetime.date.today(), entry)
        prompt_role.assert_not_called()

    push_call = authenticated_responses.calls[-1]
    assert "role_id=2" in push_call.request.body


def test_push_returns_backend_messages(authenticated_responses, backend):
    success_response = {
        "success": True,
        "messages": [{"text": "Hello world", "type": "warning"}],
    }

    authenticated_responses.replace(
        responses.POST,
        urls["timesheets"],
        body=json.dumps(success_response),
        status=200,
        content_type="application/json",
    )
    entry = Entry(alias="alias1", duration=1, description="")
    additional_info = backend.push_entry(datetime.date.today(), entry)

    assert "Hello world" in additional_info


@pytest.mark.parametrize("alias", ["alias1", "alias_do_not_ask_for_role"])
def test_individual_action_flag(authenticated_responses, backend, alias):
    require_role(authenticated_responses)
    entry = Entry(alias=alias, duration=1, description="")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        prompt_role.return_value = None
        backend.push_entry(datetime.date.today(), entry)

    push_call = authenticated_responses.calls[-1]
    assert "individual_action=true" in push_call.request.body
    assert "role_id" not in push_call.request.body


def test_push_alias_without_required_role_works(authenticated_responses, backend):
    entry = Entry(alias="alias_do_not_ask_for_role", duration=1, description="")
    backend.push_entry(datetime.date.today(), entry)

    push_call = authenticated_responses.calls[-1]
    assert "individual_action" not in push_call.request.body
    assert "role_id" not in push_call.request.body


def test_latest_role_is_selected(authenticated_responses, backend):
    require_role(authenticated_responses)
    entry = Entry(alias="alias1", duration=1, description="")

    with patch("click.termui.visible_prompt_func") as patched_input:
        patched_input.side_effect = ["", "n"]
        backend.push_entry(datetime.date.today(), entry)

    push_call = authenticated_responses.calls[-1]
    assert "role_id=2" in push_call.request.body


def test_latest_role_is_not_proposed_when_not_available(
    authenticated_responses, backend, capsys
):
    require_role(authenticated_responses)
    authenticated_responses.replace(
        responses.GET,
        urls["latestActivityRoles"],
        body=json.dumps({"success": True, "data": {1: "999"}}),
        status=200,
        content_type="application/json",
    )
    entry = Entry(alias="alias1", duration=1, description="")

    with patch("click.termui.visible_prompt_func") as patched_input:
        patched_input.return_value = "c"
        with pytest.raises(PushEntryFailed):
            backend.push_entry(datetime.date.today(), entry)

    assert "Select a role:" in capsys.readouterr().out


def test_no_default_role_proposed_when_alias_never_used(
    authenticated_responses, backend, capsys
):
    require_role(authenticated_responses)
    authenticated_responses.replace(
        responses.GET,
        urls["latestActivityRoles"],
        body=json.dumps({"success": True, "data": {}}),
        status=200,
        content_type="application/json",
    )
    entry = Entry(alias="alias1", duration=1, description="")

    with patch("click.termui.visible_prompt_func") as patched_input:
        patched_input.return_value = "c"
        with pytest.raises(PushEntryFailed):
            backend.push_entry(datetime.date.today(), entry)

    assert "Select a role:" in capsys.readouterr().out


def test_default_role_updates_between_entries(authenticated_responses, backend, capsys):
    entries = [
        Entry(alias="alias1", duration=1, description="foo"),
        Entry(alias="alias1", duration=1, description="bar"),
    ]

    with patch("click.termui.visible_prompt_func") as patched_input:
        patched_input.side_effect = ["1", "n", "", "n"]
        for entry in entries:
            require_role(authenticated_responses)
            backend.push_entry(datetime.date.today(), entry)

    assert "Select a role (leave empty for Role 2):" in capsys.readouterr().out
