---
name: on
description: Turn s0ma back on in a project where it was turned off. Use when someone says "turn s0ma back on", "use s0ma here again", or runs /s0ma:on.
---

# Turn s0ma back on in this project

s0ma was turned off for this project by one key in a small file of the
person's own, `.s0ma/preferences.json`. Turning it back on is taking that key
out.

## 1. Take the key out

Open `.s0ma/preferences.json` in the project folder, the folder this session
was started in (`s0ma-launch prefs` names it on its `Project:` line), with your
own file tools:

1. If there is no such file, or it has no `"s0ma"` key, s0ma is already on
   here: say so and stop.
2. If it holds a JSON object, remove the `"s0ma"` key and keep every other key
   just as it was. If nothing is left, leave `{}`; do not delete the file
   unless they ask.
3. If it holds anything else, show the person what is in it and ask what to do
   before you change it.
4. Write valid JSON, and never touch any other file.

## 2. Answer

Say this, word for word:

> s0ma is back on in this project.

From now on s0ma is used here the way the person's other preferences say;
`/s0ma:preferences` reads and changes those. Run `s0ma-launch prefs` if you
want to check: its first line ends with "In this project: s0ma is on" and
whatever this project still sets.
