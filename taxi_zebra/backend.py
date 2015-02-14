from __future__ import unicode_literals

from datetime import datetime
import logging
import requests

from taxi.alias import alias_database
from taxi.backends.exceptions import PushEntryFailedException
from taxi.projects import Activity, Project

logger = logging.getLogger(__name__)


class ZebraBackend(object):
    def __init__(self, login, password, host, port, path, options):
        self.login = login
        self.password = password
        self.host = host
        self.port = int(port) if port else 443
        self.path = path

        if not self.path.startswith('/'):
            self.path = '/' + self.path

        self.session = requests.Session()

    def get_full_url(self, url):
        return 'https://{host}:{port}{base_path}{url}'.format(
            host=self.host, port=self.port, base_path=self.path, url=url
        )

    def authenticate(self):
        login_url = self.get_full_url('/login/user/%s.json' % self.login)
        parameters_dict = {
            'username': self.login,
            'password': self.password,
        }

        self.session.post(login_url, data=parameters_dict)

    def push_entry(self, date, entry):
        post_url = self.get_full_url('/timesheet/create/.json')

        mapping = alias_database[entry.alias]
        parameters = {
            'time':         entry.hours,
            'project_id':   mapping.mapping[0],
            'activity_id':  mapping.mapping[1],
            'day':          date.day,
            'month':        date.month,
            'year':         date.year,
            'description':  entry.description,
        }

        response = self.session.post(post_url, data=parameters).json()

        if 'exception' in response:
            error = response['exception']['message']
            raise PushEntryFailedException(error)
        elif 'error' in response['command']:
            error = None
            for element in response['command']['error']:
                if 'Project' in element:
                    error = element['Project']
                    break

            if not error:
                error = "Unknown error message"

            raise PushEntryFailedException(error)

    def get_projects(self):
        projects_url = self.get_full_url('project/all.json')

        response = self.session.get(projects_url).json()
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
