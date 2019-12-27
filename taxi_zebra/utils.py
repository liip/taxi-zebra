from taxi.aliases import Mapping, aliases_database


def get_role_id_from_alias(alias):
    try:
        mapping = aliases_database[alias]
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


def update_alias_mapping(settings, alias, new_mapping):
    """
    Override `alias` mapping in the user configuration file with the given `new_mapping`, which should be a tuple with
    2 or 3 elements (in the form `(project_id, activity_id, role_id)`).
    """
    mapping = aliases_database[alias]
    new_mapping = Mapping(mapping=new_mapping, backend=mapping.backend)
    aliases_database[alias] = new_mapping
    settings.add_alias(alias, new_mapping)
    settings.write_config()
