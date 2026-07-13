"""Fixture app entrypoint."""
import os

import requests
from pkg.core import add


def main():
    print(add(2, 3), os.sep, requests.__name__)


if __name__ == "__main__":
    main()
