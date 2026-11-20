"""Comicify: product comics from VCS-tracked structured intermediates."""


def main() -> None:
    from .cli import app

    app()
