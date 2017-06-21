import datetime

import click

from taxi.commands.base import cli, get_timesheet_collection_for_context
from taxi.plugins import plugins_registry

from .backend import ZebraBackend


def hours_to_days(hours):
    """
    Convert the given amount of hours to a 2-tuple `(days, hours)`.
    """
    days = hours // 8
    hours_left = hours % 8

    return days, hours_left


@cli.group()
def zebra():
    """
    Zebra-related commands.
    """
    pass


def signed_number(number):
    """
    Return the given number as a string with a sign in front of it, ie. `+` if the number is positive, `-` otherwise.
    """
    if number <= 0:
        return str(number)
    else:
        return '+' + str(number)


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
    backend = plugins_registry.get_backends_by_class(ZebraBackend)[0]

    timesheet_collection = get_timesheet_collection_for_context(ctx, None)
    hours_to_be_pushed = timesheet_collection.get_hours(pushed=False, ignored=False, unmapped=False)

    today = datetime.date.today()
    user_info = backend.get_user_info(0)
    timesheets = backend.get_timesheets(get_first_dow(today), get_last_dow(today))
    total_duration = sum([float(timesheet['time']) for timesheet in timesheets])

    vacation = hours_to_days(user_info['data']['vacation']['difference'])
    vacation_balance = '{0} days, {1} hours'.format(*vacation)

    hours_balance = user_info['data']['hours']['hours']['balance']

    click.echo("Hours balance: {}".format(signed_number(hours_balance)))
    click.echo("Hours balance after push: {}".format(signed_number(hours_balance + hours_to_be_pushed)))
    click.echo("Hours done this week: {}".format(total_duration))
    click.echo("Vacation left: {}".format(vacation_balance))
