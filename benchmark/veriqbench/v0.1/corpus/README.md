# Veriq Bench v0.1 bug corpus

`mutants.jsonl`: 1036 mutants, one JSON object per line, of the 28 hard-round circuits (seed 2026).
`correct.jsonl`: the 28 original circuits (all verified correct), usable as negatives.
Field definitions: [../SCHEMA.md](../SCHEMA.md). Score a detector with `veriq bench corpus-eval --detector X`.
