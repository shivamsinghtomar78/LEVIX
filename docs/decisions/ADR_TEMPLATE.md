# ADR-NNNN - <the decision, in one line>

Status: accepted | proposed | superseded by ADR-XXXX
Date: YYYY-MM-DD

## Context

What forces a choice, stated in facts a reader can check. Name the alternatives in a
table and say what each one costs - "we picked lazy loading because it is nicer" is not a
Context, "importing Tube at startup pulls yt-dlp into `levix --help`" is.

## Decision

The thing that is now true, with the code or configuration that says it. If a detail is
load-bearing because of a bug it fixed, say so here and name the bug.

## Consequences

What this buys, and what it costs. Costs are not footnotes: a hole this decision leaves
open (an unenforced permission, a missing SDK export, a claim that cannot be made on one
operating system) belongs in this section and in
`docs/roadmap/CURRENT_STATUS.md`, in the same words.

## Verification

Which tests prove the decision, by file and count, and what is **not** verified. A number
here must come from a run, not from an intention.
