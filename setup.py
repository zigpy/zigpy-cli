import pathlib

from setuptools import setup, find_packages

import zigpy_cli
import zigpy_cli.const

setup(
    name="zigpy-cli",
    version=zigpy_cli.__version__,
    description="Unified command line interface for zigpy radios",
    long_description=(pathlib.Path(__file__).parent / "README.md").read_text(),
    long_description_content_type="text/markdown",
    url="https://github.com/zigpy/zigpy-cli",
    author="puddly",
    author_email="puddly3@gmail.com",
    license="GPL-3.0",
    entry_points={"console_scripts": ["zigpy=zigpy_cli.__main__:cli"]},
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=[
        "zigpy",
        "click",
        "coloredlogs",
        "scapy",
    ],
    extras_require={
        # [all] pulls in all radio libraries
        "all": zigpy_cli.const.RADIO_TO_PYPI.values(),
        "testing": [
            "pytest>=5.4.5",
            "pytest-asyncio>=0.12.0",
            "pytest-timeout",
            "pytest-mock",
            "pytest-cov",
            "coveralls",
            'asynctest; python_version < "3.8.0"',
        ],
    },
)
