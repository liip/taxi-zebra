import datetime
import json
from unittest.mock import patch

import pytest
import responses
import taxi.aliases
from taxi.timesheet.entry import Entry
from taxi.aliases import Mapping
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
def backend(aliases_database):
    yield ZebraBackend(
        username=username, password="foobar", hostname=hostname, port=443,
        path="", options={}, context={"view": TtyUi()}
    )


@pytest.fixture
def authenticated_responses(mocked_responses):
    user_info = {
        "success": True,
        "data": {
            "roles": {
                2: {"id": 2, "parent_id": 1, "full_name": "Role"},
            }
        }
    }

    mocked_responses.add(responses.POST,
                         urls["login"],
                         body="{}", status=200, content_type="application/json")
    mocked_responses.add(responses.GET,
                         urls["user_info"], body=json.dumps(user_info),
                         status=200, content_type="application/json")

    yield mocked_responses


def test_role_is_prompted_when_needed(authenticated_responses, backend):
    success_response = {"success": True}
    fail_response = {"errorCode": "role_needed"}
    role = Role(id="2", parent_id="1", full_name="Role")

    authenticated_responses.add(
        responses.POST, urls["timesheets"], body=json.dumps(fail_response),
        status=400, content_type="application/json"
    )
    authenticated_responses.add(
        responses.POST, urls["timesheets"], body=json.dumps(success_response),
        status=200, content_type="application/json"
    )
    entry = Entry(alias="alias1", duration=1, description="")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        prompt_role.return_value = role
        backend.push_entry(datetime.date.today(), entry)

        prompt_role.assert_called_once_with(
            entry, [role], {"view": backend.context["view"]}
        )

    push_call = authenticated_responses.calls[-1]
    assert "role_id={}".format(role.id) in push_call.request.body
    assert "individual_action=false" in push_call.request.body


def test_role_is_not_prompted_when_not_needed(authenticated_responses, backend):
    success_response = {"success": True}

    authenticated_responses.add(
        responses.POST, urls["timesheets"], body=json.dumps(success_response),
        status=200, content_type="application/json"
    )
    entry = Entry(alias="alias1", duration=1, description="")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        backend.push_entry(datetime.date.today(), entry)
        prompt_role.assert_not_called()


def test_role_is_not_prompted_when_alias_has_role(authenticated_responses,
                                                  backend, aliases_database):
    success_response = {"success": True}

    authenticated_responses.add(
        responses.POST, urls["timesheets"], body=json.dumps(success_response),
        status=200, content_type="application/json"
    )
    entry = Entry(alias="alias2", duration=1, description="")
    aliases_database["alias2"] = Mapping(mapping=("1", "1", "2"), backend="local")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        backend.push_entry(datetime.date.today(), entry)
        prompt_role.assert_not_called()

    push_call = authenticated_responses.calls[-1]
    assert "role_id=2" in push_call.request.body


def test_push_returns_backend_messages(authenticated_responses, backend):
    success_response = {"success": True, "messages": [{"text": "Hello world",
                                                       "type": "warning"}]}

    authenticated_responses.add(
        responses.POST, urls["timesheets"], body=json.dumps(success_response),
        status=200, content_type="application/json"
    )
    entry = Entry(alias="alias1", duration=1, description="")
    additional_info = backend.push_entry(datetime.date.today(), entry)

    assert "Hello world" in additional_info


@pytest.mark.parametrize("alias", ["alias1", "alias_do_not_ask_for_role"])
def test_individual_action_flag(authenticated_responses, backend, alias):
    success_response = {"success": True}
    fail_response = {"errorCode": "role_needed"}

    authenticated_responses.add(
        responses.POST, urls["timesheets"], body=json.dumps(fail_response),
        status=400, content_type="application/json"
    )
    authenticated_responses.add(
        responses.POST, urls["timesheets"], body=json.dumps(success_response),
        status=200, content_type="application/json"
    )
    entry = Entry(alias=alias, duration=1, description="")

    with patch("taxi_zebra.backend.prompt_role") as prompt_role:
        prompt_role.return_value = None
        backend.push_entry(datetime.date.today(), entry)

    push_call = authenticated_responses.calls[-1]
    assert "individual_action=true" in push_call.request.body
    assert "role_id" not in push_call.request.body


def test_push_alias_without_required_role_works(authenticated_responses, backend):
    authenticated_responses.add(
        responses.POST,
        urls["timesheets"],
        body=json.dumps({"success": True}),
        status=200,
        content_type="application/json",
    )
    entry = Entry(alias="alias_do_not_ask_for_role", duration=1, description="")
    backend.push_entry(datetime.date.today(), entry)

    push_call = authenticated_responses.calls[-1]
    assert "individual_action" not in push_call.request.body
    assert "role_id" not in push_call.request.body
