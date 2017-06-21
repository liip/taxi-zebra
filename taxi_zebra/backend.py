from __future__ import unicode_literals

from datetime import datetime
from functools import wraps
import logging

import requests
from six.moves.urllib import parse

from taxi import __version__ as taxi_version
from taxi.aliases import aliases_database
from taxi.backends import BaseBackend, PushEntryFailed
from taxi.exceptions import TaxiException
from taxi.projects import Activity, Project

logger = logging.getLogger(__name__)


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
    def push_entry(self, date, entry):
        post_url = self.get_api_url('/timesheets/')

        mapping = aliases_database[entry.alias]
        parameters = {
            'time': entry.hours,
            'project_id': mapping.mapping[0],
            'activity_id': mapping.mapping[1],
            'date': date.strftime('%Y-%m-%d'),
            'description': entry.description,
        }

        try:
            response = self._session.post(post_url, data=parameters).json()
        except ValueError:
            raise PushEntryFailed(
                "Got a non-JSON response when trying to push timesheet"
            )

        if not response['success']:
            try:
                error = response['error']
            except KeyError:
                error = "Unknown error message"

            raise PushEntryFailed(error)

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
    def get_user_info(self, user_id):
        user_info_url = self.get_api_url('/user/{}'.format(user_id))
        return self._session.get(user_info_url).json()

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
