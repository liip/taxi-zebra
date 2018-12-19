from __future__ import unicode_literals

import logging
from datetime import datetime
from functools import wraps

import click
import requests
from PyInquirer import Separator, prompt
from six.moves.urllib import parse

from taxi import __version__ as taxi_version
from taxi.aliases import Mapping, aliases_database
from taxi.backends import BaseBackend, PushEntryFailed
from taxi.exceptions import TaxiException
from taxi.projects import Activity, Project

logger = logging.getLogger(__name__)


class CancelInput(Exception):
    pass


def needs_authentication(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        args[0].authenticate()
        return f(*args, **kwargs)

    return wrapper


def get_role_from_entry(entry):
    try:
        mapping = aliases_database[entry.alias]
    except KeyError:
        role_id = None
    else:
        try:
            role_id = mapping.mapping[2]
        except IndexError:
            role_id = None

    return role_id


def to_zebra_params(params):
    """
    Transforms the given `params` dict to values that are understood by Zebra (eg. False is represented as 'false')
    """
    def to_zebra_value(value):
        transform_funcs = {
            bool: lambda v: 'true' if v else 'false',
        }

        return transform_funcs.get(type(value), lambda v: v)(value)

    return {param: to_zebra_value(value) for param, value in params.items()}


def show_response_messages(response_json):
    """
    Show all messages in the `messages` key of the given dict.
    """
    message_type_kwargs = {
        'warning': {'fg': 'yellow'},
        'error': {'fg': 'red'},
    }
    for message in response_json.get('messages', []):
        click.secho(message['text'], **message_type_kwargs.get(message['type'], {}))


def input_role(roles):
    individual_action = object()
    choices = list(((int(item[0]), item[1]) for item in roles.items())) + [
        (None, Separator()),
        # Using `None` as a value would make PyInquirer ignore the answer
        (individual_action, "Individual action ❮ YOLO"),
        (None, "Cancel, skip this entry for now"),
    ]

    selected_role_id = prompt([{
        'type': 'list',
        'name': 'role',
        'choices': [{'name': choice[1], 'value': choice[0]} for choice in choices],
        'message': 'In which role do you want to push this entry?',
    }]).get('role', -1)

    if selected_role_id == -1:
        raise CancelInput()
    elif selected_role_id == individual_action:
        selected_role_id = None

    return selected_role_id


class ZebraBackend(BaseBackend):
    def __init__(self, *args, **kwargs):
        super(ZebraBackend, self).__init__(*args, **kwargs)

        self.port = self.port if self.port else 443

        if not self.path.startswith('/'):
            self.path = '/' + self.path

        if not self.path.endswith('/'):
            self.path += '/'

        self._authenticated = False
        self._session = requests.Session()
        self._session.headers.update(
            {'user-agent': 'Taxi {}'.format(taxi_version)}
        )
        self._user_info = None

    def get_api_url(self, url):
        absolute_url = self.get_full_url('/api/v2{url}'.format(url=url))

        if not self.password:
            absolute_url = self.append_token(absolute_url)

        return absolute_url

    def get_full_url(self, url):
        # Remove slash at the start of the string since self.path already ends
        # with a slash
        url = url.lstrip('/')

        return 'https://{host}:{port}{base_path}{url}'.format(
            host=self.hostname, port=self.port, base_path=self.path, url=url
        )

    def append_token(self, url):
        split_url = list(parse.urlsplit(url))

        # Add the token parameter to the query string, then rebuild the URL
        qs = parse.parse_qs(split_url[3])
        qs['token'] = self.username
        split_url[3] = parse.urlencode(qs, doseq=True)
        url_with_token = parse.urlunsplit(split_url)

        return url_with_token

    def authenticate(self):
        if self._authenticated or not self.password:
            return

        login_url = self.get_full_url('/login/user/%s.json' % self.username)
        parameters_dict = {
            'username': self.username,
            'password': self.password,
        }

        try:
            self._session.post(login_url, data=parameters_dict).json()
        except ValueError:
            raise TaxiException("Login failed, please check your credentials")

        self._authenticated = True

    @needs_authentication
    def _push_entry(self, date, entry, role_id, *args, **kwargs):
        post_url = self.get_api_url('/timesheets/')

        mapping = aliases_database[entry.alias]

        parameters = dict({
            'time': entry.hours,
            'project_id': mapping.mapping[0],
            'activity_id': mapping.mapping[1],
            'role_id': role_id,
            'date': date.strftime('%Y-%m-%d'),
            'description': entry.description,
        }, **kwargs)

        return self._session.post(post_url, data=to_zebra_params(parameters))

    @needs_authentication
    def push_entry(self, date, entry):
        user_roles = self.get_user_info()['roles']
        role_id = get_role_from_entry(entry)

        response = self._push_entry(date, entry, role_id=role_id)

        try:
            response_json = response.json()
        except ValueError:
            raise PushEntryFailed(
                "Got a non-JSON response when trying to push timesheet"
            )

        show_response_messages(response_json)

        if not response:
            if response_json.get('errorCode') == 'role_needed':
                click.secho("\nYou're trying to push \"{}\" on the {} alias, which doesn't have any role set.\n".format(
                    entry.description, entry.alias
                ), fg='yellow')

                try:
                    role_id = input_role(user_roles)
                except CancelInput:
                    raise PushEntryFailed("Skipped")

                if role_id is not None:
                    create_alias = prompt({
                        'type': 'confirm',
                        'message': "Make the {} alias always use this role?".format(entry.alias),
                        'name': 'create_alias'
                    })

                    if create_alias['create_alias']:
                        mapping = aliases_database[entry.alias]
                        new_mapping = Mapping(mapping=mapping.mapping[:2] + (role_id,), backend=mapping.backend)
                        # Replace the mapping in the aliases database for the next entries
                        aliases_database[entry.alias] = new_mapping
                        self.context['settings'].add_alias(entry.alias, new_mapping)
                        self.context['settings'].write_config()

                        click.secho("Alias {} now points to the role {}".format(
                            entry.alias, user_roles[role_id]
                        ), fg='green')

                response = self._push_entry(date, entry, role_id=role_id, individual_action=role_id is None)
                response_json = response.json()
                show_response_messages(response_json)

        if not response_json['success']:
            try:
                error = response_json['error']
            except KeyError:
                error = "Unknown error message"

            raise PushEntryFailed(error)

        return "individual action" if not role_id else "as {}".format(user_roles[role_id])

    @needs_authentication
    def get_projects(self):
        projects_url = self.get_api_url('/projects/')

        try:
            response = self._session.get(projects_url)
            projects = response.json()
        except ValueError:
            raise TaxiException(
                "Unexpected response from the server (%s).  Check your "
                "credentials" % response.content
            )
        projects_list = []
        date_attrs = (('start_date', 'startdate'), ('end_date', 'enddate'))

        for project in projects['data']:
            p = Project(int(project['id']), project['name'],
                        Project.STATUS_ACTIVE, project['description'],
                        project['budget'])

            for date_attr, proj_date in date_attrs:
                try:
                    date = datetime.strptime(project[proj_date],
                                             '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    date = None

                setattr(p, date_attr, date)

            for activity in project['activities']:
                a = Activity(int(activity['id']), activity['name'],
                             activity['rate'])
                p.add_activity(a)

                if activity['alias']:
                    p.aliases[activity['alias']] = activity['id']

            projects_list.append(p)

        return projects_list

    @needs_authentication
    def get_user_info(self):
        if getattr(self, '_user_info', None) is None:
            user_info_url = self.get_api_url('/users/me')
            data = self._session.get(user_info_url).json()['data']

            # Roles keys (ids) are strings. Cast them as ints
            data['roles'] = {int(key): value for key, value in data['roles'].items()}

            self._user_info = data

        return self._user_info

    @needs_authentication
    def get_timesheets(self, start_date, end_date=None):
        if not end_date:
            end_date = datetime.date.today()

        timesheet_url = self.get_api_url('/timesheets')
        request_params = {
            'start_date': start_date,
            'end_date': end_date,
        }

        return self._session.get(timesheet_url, params=request_params).json()['data']['list']
