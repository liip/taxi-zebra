import logging
from collections import namedtuple
from datetime import datetime
from functools import wraps

import click
import requests
from urllib import parse
from taxi import __version__ as taxi_version
from taxi.aliases import aliases_database
from taxi.backends import BaseBackend, PushEntryFailed
from taxi.exceptions import TaxiException
from taxi.projects import Activity, Project

from .ui import prompt_role, format_response_messages
from .utils import get_role_id_from_alias, to_zebra_params


logger = logging.getLogger(__name__)


Role = namedtuple('Role', ['id', 'parent_id', 'full_name'])


def needs_authentication(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        args[0].authenticate()
        return f(*args, **kwargs)

    return wrapper


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

    def zebra_request(self, method, url, **kwargs):
        response = self._session.request(method=method, url=url, **kwargs)

        if response.status_code in {401, 403}:
            raise TaxiException("Login failed, please check your credentials")

        return response

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
            self.zebra_request('post', login_url, data=parameters_dict).json()
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

        return self.zebra_request('post', post_url, data=to_zebra_params(parameters))

    @needs_authentication
    def push_entry(self, date, entry):
        user_roles = self.get_user_roles()
        alias_role_id = get_role_id_from_alias(entry.alias)

        response = self._push_entry(date, entry, role_id=alias_role_id if alias_role_id != "0" else None)
        response_json = response.json()

        if not response:
            error_code = response_json.get('errorCode')
            if error_code in {'role_needed', 'role_invalid'}:
                if error_code == 'role_needed':
                    prompt = "You're trying to push the following entry to an activity which doesn't have any associated role:"
                elif error_code == 'role_invalid':
                    prompt = "You're trying to use a role you don't have (anymore):"
                else:
                    prompt = "You can't use that role:"

                click.secho("\n{}\n\n{}\n".format(
                    prompt, self.context['view'].get_entry_status(entry)
                ), fg='yellow')

                selected_role = prompt_role(entry, list(user_roles.values()), self.context)
                selected_role_id = selected_role.id if selected_role else None

                response = self._push_entry(
                    date, entry, role_id=selected_role_id,
                    individual_action=selected_role_id is None
                )
                response_json = response.json()
        else:
            selected_role = user_roles[alias_role_id] if alias_role_id else None

        if not response_json['success']:
            error = response_json.get('error', "Unknown error")
            raise PushEntryFailed(error)

        additional_info = "individual action" if not selected_role else "as {}".format(selected_role.full_name)
        messages = format_response_messages(response_json)

        return ". ".join([additional_info] + messages)

    @needs_authentication
    def get_projects(self):
        projects_url = self.get_api_url('/projects/')

        try:
            response = self.zebra_request('get', projects_url)
            projects = response.json()
        except ValueError:
            raise TaxiException(
                "Unexpected response from the server (%s).  Check your "
                "credentials" % response.content
            )
        projects_list = []
        date_attrs = ('start_date', 'end_date')

        for project in projects['data']:
            team = str(project['circle_id']) if project['circle_id'] else None
            p = Project(project['id'], project['name'],
                        Project.STATUS_ACTIVE, project['description'],
                        project['budget'], team=team)

            for date_attr in date_attrs:
                try:
                    date = datetime.strptime(project[date_attr],
                                             '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    date = None

                setattr(p, date_attr, date)

            for activity in project['activities']:
                a = Activity(activity['id'], activity['name'])
                p.add_activity(a)

                if activity['alias']:
                    p.aliases[activity['alias']] = activity['id']

            projects_list.append(p)

        return projects_list

    @needs_authentication
    def get_user_info(self):
        if getattr(self, '_user_info', None) is None:
            user_info_url = self.get_api_url('/users/me')
            data = self.zebra_request('get', user_info_url).json()['data']

            self._user_info = data

        return self._user_info

    def get_user_roles(self):
        def zebra_role_to_role(id_, role):
            if isinstance(role, dict):
                return Role(
                    id=str(id_),
                    parent_id=str(role['parent_id']) if role['parent_id'] else None,
                    full_name=role['full_name']
                )
            else:
                return Role(id=str(id_), parent_id=None, full_name=role)

        user_info = self.get_user_info()
        roles = {
            str(id_): zebra_role_to_role(id_, role)
            for id_, role in user_info.get('roles', {}).items()
        }

        return roles

    @needs_authentication
    def get_timesheets(self, start_date, end_date=None):
        if not end_date:
            end_date = datetime.date.today()

        timesheet_url = self.get_api_url('/timesheets')
        request_params = {
            'start_date': start_date,
            'end_date': end_date,
        }

        return self.zebra_request('get', timesheet_url, params=request_params).json()['data']['list']
