#!/usr/bin/env python
from setuptools import find_packages, setup
from taxi_zebra import __version__


install_requires = [
    'requests>=2.3.0',
    'taxi>=4.3.0',
    'six>=1.9.0',
]

setup(
    name='taxi_zebra',
    version=__version__,
    packages=find_packages(),
    description='Zebra backend for Taxi',
    author='Sylvain Fankhauser',
    author_email='sylvain.fankhauser@liip.ch',
    url='https://github.com/sephii/taxi-zebra',
    install_requires=install_requires,
    license='wtfpl',
    entry_points={
        'taxi.backends': 'zebra = taxi_zebra.backend:ZebraBackend',
        'taxi.commands': ['zebra = taxi_zebra.commands'],
    }
)
