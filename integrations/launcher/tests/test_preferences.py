"""How a person wants s0ma used, and what a new session is told about it.

Two places hold a preference. The machine's are in the launcher's config file,
set with ``set use`` and ``set studi0`` (``test_set.py``). A project's are in
``<project>/.s0ma/preferences.json``, which Claude writes with its own file tool
on a skill's instruction, and which the launcher only ever reads. This file
holds four things to account:

* the project's file is read the way the plugin promises - each key, and
  everything that is not one of them, ignored rather than repaired;
* ``prefs`` reports both places and what is in effect, in text and in JSON;
* the standing note the model is given says what the preferences add up to,
  and the person never sees it;
* no command here writes anything in a project, ever.

The exact sentences are written out in full rather than read from the
launcher's constants, so a test cannot pass by assembling a sentence the way
the code does.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hint_reading import OFF_LINE, parts, quiet_for_the_person

# ---------------------------------------------------------------------------
# The exact words of the standing note.
# ---------------------------------------------------------------------------

PURPOSE = (
    "s0ma is available in this session: it gives a project a living model of "
    "what it is made of - what each part is for, what it depends on, and why - "
    "so answers about the software come from the software itself."
)
IS_PROJECT = "This folder is a s0ma project."
NOT_PROJECT = "This folder is not a s0ma project."
USE_ASKED = (
    "s0ma is wanted only when asked: use it when the person asks for it, or "
    "when the folder is already a s0ma project; do not bring it into other work "
    "unasked."
)
USE_ALWAYS = (
    "The person asked for s0ma on new work on this machine, so build new work as "
    "a s0ma project without asking first; code that already exists is moved to "
    "s0ma only when they ask."
)
USE_ALWAYS_HERE = USE_ALWAYS.replace("on this machine", "in this project")
STUDI0 = {
    "always": (
        "studi0, s0ma's local visual environment, is wanted in every session: "
        "start it at the first build of each session, and say so."
    ),
    "offer": (
        "studi0, s0ma's local visual environment, is offered once per project: "
        "after a build, if studi0 is not showing, offer it once in this project "
        "and remember the answer as the /s0ma:preferences skill says."
    ),
    "asked": (
        "studi0, s0ma's local visual environment, is started only when the "
        "person asks."
    ),
}
IN_PROJECT = (
    "Edit the .s0ma sources and never the files in the build folder, and run "
    "`s0ma check` after an edit."
)
CHANGES = (
    "Any of this changes when the person says so: the /s0ma:preferences skill "
    "sets these preferences, /s0ma:off turns s0ma off in this project, and "
    "/s0ma:on turns it back on."
)

#: The note on a machine nobody has changed, in a folder that is not a s0ma
#: project. The pull request quotes this one.
DEFAULT_NOTE = " ".join([PURPOSE, NOT_PROJECT, USE_ASKED, STUDI0["offer"], CHANGES])


def expected_note(use: str, studi0: str, *, in_project: bool, use_here: bool = False) -> str:
    if use == "always":
        use_sentence = USE_ALWAYS_HERE if use_here else USE_ALWAYS
    else:
        use_sentence = USE_ASKED
    sentences = [PURPOSE, IS_PROJECT if in_project else NOT_PROJECT, use_sentence, STUDI0[studi0]]
    if in_project:
        sentences.append(IN_PROJECT)
    sentences.append(CHANGES)
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_update_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """The toolchains here are older than the launcher, and with no key that is
    a line for the person about the plugin's newer s0ma. These tests are about
    the note, so the update lines are switched off the ordinary way."""
    monkeypatch.setenv("S0MA_UPDATE", "off")


def write_prefs(project: Path, content: str) -> Path:
    """Write the project's file the way Claude would: a folder, then the file."""
    path = project / ".s0ma" / "preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_machine(launcher: ModuleType, home: Path, **fields: str) -> None:
    config = launcher.default_config()
    config.update(fields)
    path = launcher.config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, sort_keys=True) + "\n", encoding="utf-8")


def make_s0ma_project(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pyproject.toml").write_text(
        '[project]\nname = "shop"\n\n[tool.s0ma]\nmode = "dev"\n', encoding="utf-8"
    )
    return folder


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Every entry under *root*: a file's bytes, or ``None`` for a folder."""
    taken: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*")):
        taken[str(path)] = path.read_bytes() if path.is_file() else None
    return taken


def prefs_json(run_cli: Any) -> dict[str, Any]:
    code, out, err = run_cli("prefs", "--json")
    assert (code, err) == (0, "")
    data = json.loads(out)
    assert isinstance(data, dict)
    return data


# ---------------------------------------------------------------------------
# The project's file, read.
# ---------------------------------------------------------------------------


def test_no_file_is_nothing_set(launcher: ModuleType, project: Path) -> None:
    own = launcher.read_project_preferences(project)
    assert own.path == project / ".s0ma" / "preferences.json"
    assert (own.exists, own.readable, own.off, own.use, own.studi0) == (
        False,
        False,
        False,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"s0ma": "off"}', (True, None, None)),
        ('{"s0ma": "on"}', (False, None, None)),
        ('{"s0ma": "OFF"}', (False, None, None)),
        ('{"s0ma": false}', (False, None, None)),
        ('{"use": "always"}', (False, "always", None)),
        ('{"use": "asked"}', (False, "asked", None)),
        ('{"use": "sometimes"}', (False, None, None)),
        ('{"use": 1}', (False, None, None)),
        ('{"studi0": "always"}', (False, None, "always")),
        ('{"studi0": "asked"}', (False, None, "asked")),
        ('{"studi0": "offer"}', (False, None, None)),
        ('{"studi0": ["always"]}', (False, None, None)),
        ('{"colour": "blue", "use": "always"}', (False, "always", None)),
        (
            '{"s0ma": "off", "use": "always", "studi0": "asked", "x": 1}',
            (True, "always", "asked"),
        ),
    ],
    ids=[
        "off",
        "on",
        "off in capitals",
        "off as false",
        "use always",
        "use asked",
        "use wrong value",
        "use not a string",
        "studi0 always",
        "studi0 asked",
        "studi0 offer is not a project value",
        "studi0 not a string",
        "unknown key ignored",
        "everything",
    ],
)
def test_each_key_and_every_value_that_is_not_one(
    launcher: ModuleType,
    project: Path,
    content: str,
    expected: tuple[bool, str | None, str | None],
) -> None:
    write_prefs(project, content)
    own = launcher.read_project_preferences(project)
    assert (own.exists, own.readable) == (True, True)
    assert (own.off, own.use, own.studi0) == expected


@pytest.mark.parametrize(
    "content",
    ["{ not json", '["s0ma", "off"]', '[{"s0ma": "off"}]', '"off"', "", "null"],
    ids=["not json", "a list", "a list holding the key", "a string", "empty", "null"],
)
def test_a_file_that_is_not_an_object_counts_as_no_file(
    launcher: ModuleType, project: Path, content: str
) -> None:
    path = write_prefs(project, content)
    own = launcher.read_project_preferences(project)
    assert (own.exists, own.readable, own.off, own.use, own.studi0) == (
        True,
        False,
        False,
        None,
        None,
    )
    assert path.read_text(encoding="utf-8") == content, "never repaired"
    assert sorted(p.name for p in path.parent.iterdir()) == ["preferences.json"]


def test_a_folder_where_the_file_should_be_is_survivable(
    launcher: ModuleType, project: Path
) -> None:
    (project / ".s0ma" / "preferences.json").mkdir(parents=True)
    own = launcher.read_project_preferences(project)
    assert (own.exists, own.readable, own.off) == (True, False, False)


def test_the_file_is_read_from_the_project_folder_and_nowhere_above_it(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule as the pin: no search upwards."""
    write_prefs(tmp_path, '{"s0ma": "off"}')
    inner = tmp_path / "inner"
    inner.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(inner))
    assert launcher.read_project_preferences(launcher.project_dir()).off is False


# ---------------------------------------------------------------------------
# Knowing a s0ma project.
# ---------------------------------------------------------------------------


def test_a_folder_with_a_tool_s0ma_table_is_a_s0ma_project(
    launcher: ModuleType, tmp_path: Path
) -> None:
    root = make_s0ma_project(tmp_path / "shop")
    assert launcher.s0ma_project_root(root) == root


def test_any_path_inside_the_project_finds_its_root(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """A later change asks about a file being edited, so a path of any kind works."""
    root = make_s0ma_project(tmp_path / "shop")
    deep = root / "src" / "shop"
    deep.mkdir(parents=True)
    source = deep / "orders.s0ma"
    source.write_text("", encoding="utf-8")
    assert launcher.s0ma_project_root(deep) == root
    assert launcher.s0ma_project_root(source) == root
    assert launcher.s0ma_project_root(deep / "not-written-yet.s0ma") == root


def test_the_nearest_pyproject_decides(launcher: ModuleType, tmp_path: Path) -> None:
    """A Python project inside a s0ma one is not a s0ma project."""
    outer = make_s0ma_project(tmp_path / "outer")
    inner = outer / "vendored"
    inner.mkdir()
    (inner / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert launcher.s0ma_project_root(inner) is None
    assert launcher.s0ma_project_root(outer) == outer


@pytest.mark.parametrize(
    "content",
    [
        '[project]\nname = "x"\n',
        "[tool.other]\nmode = 1\n",
        'tool = { s0ma = "yes" }\n',
        "[tool.s0ma\nbroken",
        "",
    ],
    ids=["no tool table", "another tool", "not a table", "cannot be parsed", "empty"],
)
def test_anything_else_is_not_a_s0ma_project(
    launcher: ModuleType, tmp_path: Path, content: str
) -> None:
    folder = tmp_path / "x"
    folder.mkdir()
    (folder / "pyproject.toml").write_text(content, encoding="utf-8")
    assert launcher.s0ma_project_root(folder) is None


def test_no_pyproject_anywhere_is_not_a_s0ma_project(
    launcher: ModuleType, project: Path
) -> None:
    assert launcher.s0ma_project_root(project) is None


# ---------------------------------------------------------------------------
# prefs: text and JSON.
# ---------------------------------------------------------------------------


def test_prefs_on_a_machine_nobody_has_changed(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    data = prefs_json(run_cli)
    assert data == {
        "schema": "s0ma-launch-prefs@1",
        "machine": {
            "config_file": launcher.config_path(isolated_home).as_posix(),
            "use": "asked",
            "studi0": "offer",
        },
        "project": {
            "dir": project.as_posix(),
            "file": (project / ".s0ma" / "preferences.json").as_posix(),
            "file_exists": False,
            "file_read": False,
            "s0ma": "on",
            "use": None,
            "studi0": None,
        },
        "in_effect": {
            "use": "asked",
            "use_from": "machine",
            "studi0": "offer",
            "studi0_from": "machine",
        },
        "off_here": False,
        "s0ma_project": {"is": False, "root": None},
    }


def test_prefs_text_on_a_machine_nobody_has_changed(
    run_cli: Any, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    code, out, err = run_cli("prefs")
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == (
        "On this Mac: s0ma only when asked, studi0 offered once per project. "
        "In this project: s0ma is on."
    )
    assert lines[1] == ""
    assert lines[2].startswith("This Mac:  use asked, studi0 offer (saved in ")
    assert "Its file:" in out and "not there, so nothing is set for this project" in out
    assert "s0ma here:     on" in out
    assert "Set here:      nothing" in out
    assert (
        "In effect:     use asked (from this machine), studi0 offer (from this machine)"
        in out
    )
    assert "s0ma project:  no" in out
    out.encode("ascii")


@pytest.mark.parametrize(
    ("platform", "word"),
    [("darwin", "Mac"), ("win32", "PC"), ("linux", "computer"), ("freebsd14", "computer")],
)
def test_the_machine_is_called_what_its_person_calls_it(
    run_cli: Any, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, platform: str, word: str
) -> None:
    monkeypatch.setattr(launcher.sys, "platform", platform)
    out = run_cli("prefs")[1]
    assert out.startswith(f"On this {word}: ")
    assert f"\nThis {word}:  " in out


def test_prefs_with_the_machine_set(
    run_cli: Any, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    run_cli("set", "use", "always")
    run_cli("set", "studi0", "always")
    data = prefs_json(run_cli)
    assert data["machine"]["use"] == "always"
    assert data["machine"]["studi0"] == "always"
    assert data["in_effect"] == {
        "use": "always",
        "use_from": "machine",
        "studi0": "always",
        "studi0_from": "machine",
    }
    first = run_cli("prefs")[1].splitlines()[0]
    assert first == (
        "On this Mac: s0ma on new work without being asked, studi0 opened at the "
        "first build of each session. In this project: s0ma is on."
    )


def test_the_project_overrides_the_machine(
    run_cli: Any, launcher: ModuleType, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    run_cli("set", "studi0", "always")
    write_prefs(project, '{"use": "always", "studi0": "asked"}')
    data = prefs_json(run_cli)
    assert data["machine"] == {
        "config_file": data["machine"]["config_file"],
        "use": "asked",
        "studi0": "always",
    }
    assert data["project"]["file_exists"] is True
    assert data["project"]["file_read"] is True
    assert (data["project"]["use"], data["project"]["studi0"]) == ("always", "asked")
    assert data["in_effect"] == {
        "use": "always",
        "use_from": "project",
        "studi0": "asked",
        "studi0_from": "project",
    }
    out = run_cli("prefs")[1]
    assert out.splitlines()[0] == (
        "On this Mac: s0ma only when asked, studi0 opened at the first build of "
        "each session. In this project: s0ma is on, with s0ma on new work without "
        "being asked and studi0 only when asked."
    )
    assert "Set here:      use always, studi0 asked" in out
    assert "use always (from this project), studi0 asked (from this project)" in out


def test_one_value_from_each_place(run_cli: Any, project: Path) -> None:
    write_prefs(project, '{"use": "always"}')
    assert prefs_json(run_cli)["in_effect"] == {
        "use": "always",
        "use_from": "project",
        "studi0": "offer",
        "studi0_from": "machine",
    }


def test_prefs_when_s0ma_is_off_here(
    run_cli: Any, launcher: ModuleType, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    write_prefs(project, '{"s0ma": "off", "use": "always"}')
    data = prefs_json(run_cli)
    assert data["off_here"] is True
    assert data["project"]["s0ma"] == "off"
    out = run_cli("prefs")[1]
    assert out.splitlines()[0] == (
        "On this Mac: s0ma only when asked, studi0 offered once per project. "
        "In this project: s0ma is off."
    )
    assert "s0ma here:     off" in out


def test_prefs_in_a_s0ma_project(
    run_cli: Any, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_s0ma_project(project)
    data = prefs_json(run_cli)
    assert data["s0ma_project"] == {"is": True, "root": project.as_posix()}
    assert f"s0ma project:  yes, at {project.as_posix()}" in run_cli("prefs")[1]


def test_prefs_says_when_the_file_could_not_be_read(
    run_cli: Any, project: Path
) -> None:
    write_prefs(project, "[1, 2]")
    data = prefs_json(run_cli)
    assert (data["project"]["file_exists"], data["project"]["file_read"]) == (True, False)
    assert data["in_effect"]["use_from"] == "machine"
    assert "there, but it could not be read as settings, so it is not used" in run_cli(
        "prefs"
    )[1]


def test_prefs_repairs_nothing_in_the_launchers_own_folder(
    run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    """A spoiled config is read as the defaults, and left exactly where it is."""
    path = launcher.config_path(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text("{ spoiled", encoding="utf-8")
    data = prefs_json(run_cli)
    assert (data["machine"]["use"], data["machine"]["studi0"]) == ("asked", "offer")
    assert path.read_text(encoding="utf-8") == "{ spoiled"
    assert sorted(p.name for p in path.parent.iterdir()) == ["config.json"]


def test_prefs_opens_no_connection(run_cli: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("prefs must never open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert run_cli("prefs")[0] == 0
    assert run_cli("prefs", "--json")[0] == 0


# ---------------------------------------------------------------------------
# The launcher never writes in a project.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [None, '{"use": "always", "studi0": "asked", "other": [1, 2]}', '{"s0ma": "off"}', "{ x"],
    ids=["no file", "a file", "off", "a spoiled file"],
)
def test_no_command_in_this_change_writes_in_the_project(
    run_cli: Any, project: Path, make_toolchain: Any, content: str | None
) -> None:
    """Byte for byte, and no file or folder added or taken away."""
    make_toolchain("0.18.0")
    make_s0ma_project(project)
    if content is not None:
        write_prefs(project, content)
    before = snapshot(project)
    for argv in (
        ("set", "use", "always"),
        ("set", "use", "asked"),
        ("set", "studi0", "always"),
        ("set", "studi0", "offer"),
        ("set", "studi0", "asked"),
        ("set", "use", "nonsense"),
        ("prefs",),
        ("prefs", "--json"),
        ("session-hint",),
    ):
        run_cli(*argv)
        assert snapshot(project) == before, f"{' '.join(argv)} changed the project"


# ---------------------------------------------------------------------------
# The standing note.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("in_project", [False, True], ids=["elsewhere", "s0ma project"])
@pytest.mark.parametrize("studi0", ["always", "offer", "asked"])
@pytest.mark.parametrize("use", ["always", "asked"])
def test_the_note_for_every_setting_on_the_machine(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    project: Path,
    make_toolchain: Any,
    use: str,
    studi0: str,
    in_project: bool,
) -> None:
    make_toolchain("0.18.0")
    write_machine(launcher, isolated_home, use=use, studi0=studi0)
    if in_project:
        make_s0ma_project(project)
    note = quiet_for_the_person(run_cli("session-hint"))
    assert note == expected_note(use, studi0, in_project=in_project)
    assert len(note) <= 1200
    assert note.isascii()
    assert "—" not in note


@pytest.mark.parametrize("in_project", [False, True], ids=["elsewhere", "s0ma project"])
@pytest.mark.parametrize("studi0", ["always", "asked"])
@pytest.mark.parametrize("use", ["always", "asked"])
def test_the_note_for_every_setting_in_the_project(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    project: Path,
    make_toolchain: Any,
    use: str,
    studi0: str,
    in_project: bool,
) -> None:
    """The project's value wins over the machine's, which here says the opposite."""
    make_toolchain("0.18.0")
    write_machine(
        launcher,
        isolated_home,
        use="asked" if use == "always" else "always",
        studi0="offer",
    )
    if in_project:
        make_s0ma_project(project)
    write_prefs(project, json.dumps({"use": use, "studi0": studi0}))
    note = quiet_for_the_person(run_cli("session-hint"))
    assert note == expected_note(use, studi0, in_project=in_project, use_here=True)


def test_the_default_note_in_full(run_cli: Any, make_toolchain: Any) -> None:
    make_toolchain("0.18.0")
    assert quiet_for_the_person(run_cli("session-hint")) == DEFAULT_NOTE


def test_the_note_is_never_shown_to_the_person(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    """Even beside a line the person does see, the note goes to the model only."""
    make_toolchain("0.18.0")
    state = launcher.default_state()
    state["entitlement"] = "not_entitled"
    path = launcher.state_path(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    message, context, note = parts(run_cli("session-hint")[1])
    assert message is not None and message.startswith("This account's access")
    assert context is None
    assert note == DEFAULT_NOTE
    assert PURPOSE not in message


def test_no_note_when_s0ma_cannot_be_used_here(run_cli: Any) -> None:
    message, context, note = parts(run_cli("session-hint")[1])
    assert message is not None and message.startswith("s0ma's tools are not available")
    assert context is not None
    assert note is None


def test_every_note_fits_its_own_limit(launcher: ModuleType, tmp_path: Path) -> None:
    """Every combination the launcher can produce, read off its own function."""
    own = launcher.read_project_preferences(tmp_path)
    longest = 0
    for use in launcher.USE_MODES:
        for studi0 in launcher.STUDI0_MODES:
            for source in ("machine", "project"):
                for root in (None, tmp_path):
                    prefs = launcher.Preferences(
                        use, studi0, own, use, source, studi0, source, root
                    )
                    note = launcher.standing_note(prefs)
                    assert note.isascii()
                    longest = max(longest, len(note))
    assert launcher.NOTE_MAX_CHARS == 1200
    assert longest <= launcher.NOTE_MAX_CHARS


# ---------------------------------------------------------------------------
# What a person says in one session reaches the next one.
# ---------------------------------------------------------------------------


def test_saying_always_use_s0ma_changes_what_the_next_session_is_told(
    run_cli: Any, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    before = quiet_for_the_person(run_cli("session-hint"))
    assert USE_ASKED in before and USE_ALWAYS not in before

    assert run_cli("set", "use", "always")[0] == 0

    after = quiet_for_the_person(run_cli("session-hint"))
    assert USE_ALWAYS in after and USE_ASKED not in after
    assert after == before.replace(USE_ASKED, USE_ALWAYS)


def test_turning_s0ma_off_here_silences_that_project_only(
    run_cli: Any, tmp_path: Path, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_toolchain("0.18.0")
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    project_a.mkdir()
    project_b.mkdir()
    write_prefs(project_a, '{"s0ma": "off"}')

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_a))
    code, out, err = run_cli("session-hint")
    assert (code, err) == (0, "")
    assert json.loads(out) == {
        "hookSpecificOutput": {
            "additionalContext": OFF_LINE,
            "hookEventName": "SessionStart",
        }
    }
    assert parts(out) == (None, OFF_LINE, None)

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_b))
    assert quiet_for_the_person(run_cli("session-hint")) == DEFAULT_NOTE


@pytest.mark.parametrize("case", ["nothing installed", "key refused", "pin missing"])
def test_off_here_outranks_every_line_the_person_would_have_seen(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    project: Path,
    make_toolchain: Any,
    case: str,
) -> None:
    if case == "key refused":
        make_toolchain("0.18.0")
        state = launcher.default_state()
        state["entitlement"] = "invalid_key"
        path = launcher.state_path(isolated_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    if case == "pin missing":
        make_toolchain("0.18.0")
        (project / ".s0ma-version").write_text("0.19.0\n", encoding="utf-8")
    write_prefs(project, '{"s0ma": "off"}')
    code, out, err = run_cli("session-hint")
    assert (code, err) == (0, "")
    assert parts(out) == (None, OFF_LINE, None)


def test_turning_s0ma_back_on_brings_the_note_back(
    run_cli: Any, project: Path, make_toolchain: Any
) -> None:
    """What the on skill does: the key goes, and the rest of the file stays."""
    make_toolchain("0.18.0")
    write_prefs(project, '{"s0ma": "off", "use": "always"}')
    assert parts(run_cli("session-hint")[1]) == (None, OFF_LINE, None)
    write_prefs(project, '{"use": "always"}')
    note = quiet_for_the_person(run_cli("session-hint"))
    assert USE_ALWAYS_HERE in note


def test_the_off_line_opens_no_socket(
    run_cli: Any, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("session-hint must never open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    write_prefs(project, '{"s0ma": "off"}')
    assert parts(run_cli("session-hint")[1]) == (None, OFF_LINE, None)
