---
name: off
description: Turn s0ma off for this project only, leaving every other project as it is. Use when someone says "turn s0ma off here", "don't use s0ma in this project", or runs /s0ma:off.
---

# Turn s0ma off in this project

This turns s0ma off for one project, the one this session was started in.
Nothing of theirs is changed or removed: you add one small file that says
s0ma is off here, and every other project on this machine stays as it was.

## 1. Write the file

Write `"s0ma": "off"` into `.s0ma/preferences.json` in the project folder,
with your own file tools:

1. The project folder is the folder this session was started in, which
   `s0ma-launch prefs` names on its `Project:` line. Never a folder above it.
2. If there is no `.s0ma/` folder there, create it.
3. If the file is already there, read it first. If it holds a JSON object,
   keep every key already in it and add `"s0ma": "off"`. If it holds anything
   else, show the person what is in it and ask before you replace it.
4. Write valid JSON: one object, such as `{"s0ma": "off"}`.
5. Never touch any other file: not `.gitignore`, not `pyproject.toml`, and
   nothing else in `.s0ma/`.

The file is the person's own, and it is not meant to be committed. If the
project is a git repository that does not ignore `.s0ma/`, say so and suggest
they add `.s0ma/` to `.gitignore` themselves.

## 2. Answer

Say this, word for word:

> s0ma is off in this project. I won't use it here, I won't check your edits, and studi0 stays closed. Nothing of yours was changed or removed; I added one small file, `.s0ma/preferences.json`, that says s0ma is off here. Say "turn s0ma back on" or `/s0ma:on` any time. To switch it off everywhere, disable the s0ma plugin in Claude's plugin manager.

## 3. From now on

For the rest of this session, do not use s0ma or its tools here, do not offer
studi0, and do not bring s0ma up unless the person does. From the next session
on, the note a session starts with says the same thing, and nothing else about
s0ma.

Run `s0ma-launch prefs` if you want to check: its first line ends with "In this
project: s0ma is off."
