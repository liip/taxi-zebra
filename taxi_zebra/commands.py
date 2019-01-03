import datetime

import click

from taxi.commands.base import cli, get_timesheet_collection_for_context
from taxi.plugins import plugins_registry
from taxi.aliases import aliases_database

from .backend import ZebraBackend


def hours_to_days(hours):
    """
    Convert the given amount of hours to a 2-tuple `(days, hours)`.
    """
    days = int(hours // 8)
    hours_left = hours % 8

    return days, hours_left


@cli.group()
def zebra():
    """
    Zebra-related commands.
    """
    pass


def signed_number(number, precision=2):
    """
    Return the given number as a string with a sign in front of it, ie. `+` if the number is positive, `-` otherwise.
    """
    prefix = '' if number <= 0 else '+'
    number_str = '{}{:.{precision}f}'.format(prefix, number, precision=precision)

    return number_str


def get_first_dow(date):
    """
    Return the first day of the week for the given date.
    """
    return date - datetime.timedelta(days=date.weekday())


def get_last_dow(date):
    """
    Return the last day of the week for the given date.
    """
    return date + datetime.timedelta(days=(6 - date.weekday()))


@zebra.command()
@click.pass_context
def balance(ctx):
    """
    Show Zebra balance.

    Like the hours balance, vacation left, etc.
    """
    def entries_filter_callback(entries_date, entry):
        backends = plugins_registry.get_available_backends()
        zebra_backends = {
            backend_name for backend_name in backends
            if isinstance(plugins_registry.get_backend(backend_name), ZebraBackend)
        }

        return (not any((entry.ignored, entry.pushed, entry.unmapped)) and entry.alias in aliases_database and
                aliases_database[entry.alias].backend in zebra_backends)

    backend = plugins_registry.get_backends_by_class(ZebraBackend)[0]

    timesheet_collection = get_timesheet_collection_for_context(ctx, None)
    hours_to_be_pushed = timesheet_collection.get_hours_by_callback(entries_filter_callback)

    today = datetime.date.today()
    user_info = backend.get_user_info()
    timesheets = backend.get_timesheets(get_first_dow(today), get_last_dow(today))
    total_duration = sum([float(timesheet['time']) for timesheet in timesheets])

    vacation = hours_to_days(user_info['data']['vacation']['difference'])
    vacation_balance = '{} days, {:.2f} hours'.format(*vacation)

    hours_balance = user_info['hours']['hours']['balance']

    click.echo("Hours balance: {}".format(signed_number(hours_balance)))
    click.echo("Hours balance after push: {}".format(signed_number(hours_balance + hours_to_be_pushed)))
    click.echo("Hours done this week: {:.2f}".format(total_duration))
    click.echo("Vacation left: {}".format(vacation_balance))
