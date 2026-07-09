# Anecdotes

Real moments from the build worth keeping — for the submission summary and demo.

## The build proved its own thesis: the BGZF near-miss

**What the tool is built to prevent, it caught in its own data pipeline on Day 1.**

While building the Turkish Variome index, the first run of `build_index.py`
stopped itself:

```
Done: scanned 245 rows in 1749s; matched 0
ERROR: 0 matched rows — refusing to write an empty/misleading index.
```

It had streamed a 2 GB file and decoded **245 rows out of 46,739,479** — and,
crucially, **nothing raised an error**. A naive pipeline would have written a
"successful" index that was 99.9995% missing and looked complete.

**Root cause.** The Turkish Variome file is **multi-member gzip (BGZF)** —
hundreds of independently-compressed gzip members concatenated together. A
single `zlib` decompressor decodes only the **first** member, sets its
end-of-stream flag, and then silently ignores every byte that follows. The
first member held 245 rows; the decoder reported success and quit. Measured
directly on the first 5 MB:

| Decode strategy | Rows recovered from 5 MB |
|---|---|
| Single `zlib` decompressor (the trap) | 246, then EOF — **5.23 MB ignored** |
| Chaining a fresh decoder per member | **121,274** (487 gzip members) |

**How the guard caught it.** Two fail-loud checks, not one:
1. The builder **refuses to write** on zero matched rows — so the truncated
   decode became a loud failure, not a silent partial dataset.
2. The fix then added an **integrity gate**: the whole download is verified
   against figshare's published **size and MD5** before anything is written.
   A truncated or corrupt download now fails loud and writes nothing.

The final build scanned all **46,739,479** rows and matched
`md5 b4e5f63d771332d5d0c942045045ddd1` before writing 6,046 demo-gene rows.

**Why it matters.** This is the project's entire thesis proven on itself: a
system that quietly returns "nothing found" is more dangerous than one that
declares its limits. *Empty ≠ clean.* A variant tool that silently accepted 245
of 46.7M rows is the same failure as a variant tool that silently treats a
failed database lookup as "benign." We built the second to be impossible; on
Day 1 the first tried to happen, and the guard held.
