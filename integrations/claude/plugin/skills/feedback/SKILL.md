---
name: feedback
description: Send feedback about s0ma to the s0ma team — you approve the exact feedback data before anything is sent.
---

# Send feedback about s0ma

Whatever the user typed after `/s0ma-feedback` is their feedback in their own words — seed the draft from it. If they typed nothing, ask ONE short question about what they want reported, then continue.

Invoking this command is itself the statement that the feedback is about s0ma, so it needs no further confirmation. (In ordinary conversation the rule is different: if someone mentions feedback without naming s0ma or kn0wthyself, ask first — other tools collect feedback too.)

Then work the journey on the `s0ma-authoring` MCP server:

1. Draft it concisely from evidence you already have: their own account, the diagnostic codes they hit, the tool or command involved. Leave unrelated source code and unrelated conversation out — never paste a file, a transcript, or a credential into the report.
2. Call `prepare_feedback` with that draft. It saves nothing and sends nothing.
3. Show the user the exact feedback data it returned, and say what its redaction report removed. Any edit of theirs means a fresh `prepare_feedback` call — the report and its fingerprint always travel together, unchanged.
4. Call `submit_feedback` with that report and fingerprint unchanged. The approval form does the asking: never state or assume that the user approved, and never read frustration as consent.
5. Relay the outcome plainly: the receipt id when it sent, or — on refusal, on failure, or in a client with no approval form — the saved draft id and the one command that finishes it from a terminal: `s0ma feedback`.

If the s0ma MCP server is not connected, run `s0ma feedback` in a terminal instead. It is the same journey, and it works in any client.
