"""Sample application two: a one-file greeting service. Input data."""

from __future__ import annotations

GREETINGS = {"en": "hello", "cy": "helo", "ga": "dia dhuit"}


def greet(name: str, language: str = "en") -> str:
    """A greeting for ``name`` in ``language``, falling back to English."""
    word = GREETINGS.get(language, GREETINGS["en"])
    return f"{word}, {name}"


def main() -> int:
    for language in sorted(GREETINGS):
        print(greet("world", language))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
