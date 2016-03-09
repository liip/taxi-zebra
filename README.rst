Zebra backend for Taxi
======================

This is the Zebra backend for `Taxi <https://github.com/sephii/taxi>`_. It
exposes the ``zebra`` protocol to push entries and fetch projects and
activities from Zebra.

Installation
------------

    pip install taxi-zebra

Usage
-----

In your ``.taxirc`` file, use the ``zebra`` protocol for your backend. For example,
if your Zebra instance is hosted at https://zebra.example.com/ you'll use the
following configuration::

    [backends]
    my_zebra_backend = zebra://username:password@zebra.example.com

If you want to use a token-based authentication, start by generating a token in
your Zebra profile, then use the token as your username, without any password::

    [backends]
    my_zebra_backend = zebra://token@zebra.example.com
