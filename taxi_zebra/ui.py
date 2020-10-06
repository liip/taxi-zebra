import inspect
from collections import namedtuple

import click

from taxi.aliases import aliases_database
from taxi.backends import PushEntryFailed

from .roles import NEVER_SAVE_ROLE_ID
from .utils import get_role_id_from_alias, update_alias_mapping


class CancelInput(Exception):
    pass


Option = namedtuple('Option', ['value', 'label', 'key', 'style'])
Option.__new__.__defaults__ = (None, {})


def format_response_messages(response_json):
    """
    Show all messages in the `messages` key of the given dict.
    """
    message_type_kwargs = {
        'warning': {'fg': 'yellow'},
        'error': {'fg': 'red'},
    }

    return [
        click.style(
            message['text'], **message_type_kwargs.get(message['type'], {})
        )
        for message in response_json.get('messages', [])
    ]


def prompt_options(message, options, default=None):
    def get_option_key(pos, option):
        return option.key if option.key is not None else pos

    enumerated_options = list(enumerate(options))
    options_by_key = [(get_option_key(i, option), option) for i, option in enumerated_options]
    options_by_key_dict = dict(options_by_key)
    try:
        default_option_id = next(
            key for key, option in options_by_key if option.value == default.value
        ) if default else None
    except StopIteration:
        default_option_id = None

    click.secho(message + "\n", bold=True)

    for option_key, option in options_by_key:
        if option.value is not None:
            click.echo(
                click.style("[{}]".format(option_key), fg='yellow',
                            **option.style)
                + " "
                + click.style(option.label, **option.style)
            )
        else:
            click.echo(option.label)

    click.echo()
    prompt_message_default = " (leave empty for {})".format(default.label) if default else ""
    prompt_message = "Select a role{}".format(prompt_message_default)

    while True:
        option_id = click.prompt(
            prompt_message,
            default=str(default_option_id) if default_option_id is not None else None,
            show_default=False
        ).lstrip('[').rstrip(']')

        try:
            option_id = int(option_id)
        except ValueError:
            pass

        try:
            return options_by_key_dict[option_id][0]
        except KeyError:
            click.secho("`{}` is not a a valid option. Please try again.".format(option_id), fg='red')

    return option_id


def input_role(roles, project_team, default_role=None):
    """
    Show a list of roles to the user and ask them to select one. Return the
    selected `Role`, or `None` if individual action was chosen.
    """
    def role_to_option(role):
        highlight = role.parent_id and role.parent_id == project_team

        return Option(
            value=role, label=role.full_name, style={'bold': True} if highlight else {}
        )

    individual_action = 'i'
    cancel = 'c'
    sorted_roles = sorted(roles, key=lambda role: role.full_name)

    options = [
        role_to_option(role) for role in sorted_roles
    ] + [
        Option(value=None, label='-----'),
        Option(value=individual_action, label="Individual action", key=individual_action),
        Option(value=cancel, label="Cancel, skip this entry for now", key=cancel),
    ]

    default_option = role_to_option(default_role) if default_role else None

    try:
        selected_role = prompt_options(
            message='In which role do you want to push this entry?', options=options, default=default_option
        )
    except click.exceptions.Abort:
        selected_role = cancel

    if selected_role == cancel:
        click.echo()
        raise CancelInput()
    elif selected_role == individual_action:
        selected_role = None

    return selected_role


def prompt_role(entry, roles, context, default_role=None):
    """
    Ask the user to choose a role in `roles` for the given `entry` and return
    it.
    """
    mapping = aliases_database[entry.alias]
    project = context['projects_db'].get(mapping.mapping[0], mapping.backend)
    project_team = project.team if project else None

    try:
        role = input_role(roles, project_team, default_role=default_role)
    except CancelInput:
        raise PushEntryFailed("Skipped")

    # Do not ask to save role association if user has requested to never be asked for it
    if role and get_role_id_from_alias(entry.alias) != NEVER_SAVE_ROLE_ID:
        click.echo("You have selected the role {}".format(click.style(role.full_name, fg='yellow')))
        prompt_kwargs = {
            'prompt_suffix': ' ',
            'type': click.Choice(['y', 'n', 'N']),
            'default': 'y'
        }

        # `show_choices` has been added in click 7.0. Support for click < 7 is needed for distributions
        # that only provide click 6 in their package managers
        if 'show_choices' in inspect.signature(click.prompt).parameters:
            prompt_kwargs['show_choices'] = False

        try:
            create_alias = click.prompt(
                "Make the {} alias always use this role? ([y]es, [n]o, [N]ever)".format(
                    click.style(entry.alias, fg='yellow')
                ), **prompt_kwargs
            )
        except click.exceptions.Abort:
            click.echo()
            raise PushEntryFailed("Skipped")

        if create_alias == 'y':
            update_alias_mapping(
                context['settings'], entry.alias,
                aliases_database[entry.alias].mapping[:2] + (str(role.id),)
            )

            click.secho("Alias {} now points to the role {}".format(
                entry.alias, role.full_name
            ), fg='green')
        elif create_alias == 'N':
            update_alias_mapping(
                context['settings'], entry.alias,
                aliases_database[entry.alias].mapping[:2] + (NEVER_SAVE_ROLE_ID,)
            )

    return role
