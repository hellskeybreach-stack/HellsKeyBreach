#!/usr/bin/env python3
from setuptools import setup

setup(
    name='hellskey-breach',
    version='1.1.0',
    description='HellsKey Breach – OSINT tool with HellsKey authentication',
    author='HellsKey',
    url='http://2dpg7coa4gi4rw2pjaor4cwwcelspqlpt2yvmu6avgk6mq3jmwz6pxad.onion',
    py_modules=['hellskey_breach'],
    install_requires=[
        'requests',
        'yaspin',
        'tldextract',
        'argcomplete',
        'rich>=10.0.0'
    ],
    entry_points={
        'console_scripts': [
            'hellskey-breach = hellskey_breach:main',
        ],
    },
)
