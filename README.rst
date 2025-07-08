Zebra backend for Taxi
======================

This is the Zebra backend for `Taxi <https://github.com/liip/taxi>`_. It
exposes the ``zebra`` protocol to push entries and fetch projects and
activities from Zebra.

Installation
------------

    taxi plugin install zebra

Usage
-----

In your ``.taxirc`` file, use the ``zebra`` protocol for your backend. For example,
if your Zebra instance is hosted at https://zebra.example.com/, after generating a
token in your Zebra profile, you'll use the following configuration::

    [backends]
    my_zebra_backend = zebra://token@zebra.example.com

Contributing
------------

To setup a development environment, create a virtual environment and run the
following command in it::

    pip install -e .

To use a specific version of Taxi, eg. if you need to also make changes to Taxi,
install it in the virtual environment in editable mode::

    pip install -e /path/to/taxi

To run the tests::

    pip install .[testing]
    pytest


Uploading a new release
-----------------------

To upload a new release just run the ``release.sh`` file which will commit and push a tag. A Github action will then upload the new release.
