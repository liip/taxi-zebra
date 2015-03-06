from __future__ import unicode_literals

from datetime import datetime
from functools import wraps
import logging
import requests

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

        self._authenticated = False
        self._session = requests.Session()

    def get_full_url(self, url):
        return 'https://{host}:{port}{base_path}{url}'.format(
            host=self.hostname, port=self.port, base_path=self.path, url=url
        )

    def authenticate(self):
        if self._authenticated:
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

        self.authenticated = True

    @needs_authentication
    def push_entry(self, date, entry):
        post_url = self.get_full_url('/timesheet/create/.json')

        mapping = aliases_database[entry.alias]
        parameters = {
            'time':         entry.hours,
            'project_id':   mapping.mapping[0],
            'activity_id':  mapping.mapping[1],
            'day':          date.day,
            'month':        date.month,
            'year':         date.year,
            'description':  entry.description,
        }

        response = self._session.post(post_url, data=parameters).json()

        if 'exception' in response:
            error = response['exception']['message']
            raise PushEntryFailed(error)
        elif 'error' in response['command']:
            error = None
            for element in response['command']['error']:
                if 'Project' in element:
                    error = element['Project']
                    break

            if not error:
                error = "Unknown error message"

            raise PushEntryFailed(error)

    @needs_authentication
    def get_projects(self):
        projects_url = self.get_full_url('project/all.json')

        response = self._session.get(projects_url).json()
        projects = response['command']['projects']['project']
        activities = response['command']['activities']['activity']
        activities_dict = {}

        for activity in activities:
            a = Activity(int(activity['id']), activity['name'],
                         activity['rate_eur'])
            activities_dict[a.id] = a

        projects_list = []
        i = 0

        for project in projects:
            p = Project(int(project['id']), project['name'],
                        project['status'], project['description'],
                        project['budget'])

            try:
                p.start_date = datetime.strptime(
                    project['startdate'], '%Y-%m-%d').date()
            except ValueError:
                p.start_date = None

            try:
                p.end_date = datetime.strptime(
                    project['enddate'], '%Y-%m-%d').date()
            except ValueError:
                p.end_date = None

            i += 1

            activities = project['activities']['activity']

            # Sometimes the activity list just contains an @attribute
            # element, in this case we skip it
            if isinstance(activities, dict):
                continue

            # If there's only 1 activity, this won't be a list but a simple
            # element
            if not isinstance(activities, list):
                activities = [activities]

            for activity in activities:
                try:
                    if int(activity) in activities_dict:
                        p.add_activity(activities_dict[int(activity)])
                except ValueError:
                    logger.warn(
                        "Cannot import activity %s for project %s because "
                        "activity id is not an int" % (activity, p.id)
                    )

            if 'activity_aliases' in project and project['activity_aliases']:
                for alias, mapping in project['activity_aliases'].items():
                    p.aliases[alias] = int(mapping)

            projects_list.append(p)

        return projects_list
