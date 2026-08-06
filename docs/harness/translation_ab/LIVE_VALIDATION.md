# Live Validation

## Input

- Course: Probability Bootcamp
- Lesson 4: Set Theory in Probability: Sample Spaces and Events
- Video ID: `b_ev4Hdzh-U`
- Duration: 24:12
- Backend/model: `codex_cli:gpt-5.4:reasoning=low`

## Fresh run

Command:

```bash
/usr/bin/time -p uv run yt2notion translation-experiment \
  "https://www.youtube.com/watch?v=b_ev4Hdzh-U&list=PLMrJAkhIeNNR3sNYvfgiKgcStwuPSts9V&index=4" \
  --config config.yaml \
  --workspace-dir workspace/translation-ab-lesson4 \
  --no-video --verbose
```

Results:

- wall time: 189.11 seconds;
- whole-chapter generation: 89.529 seconds;
- semantic-block generation: 92.724 seconds;
- acquisition and orchestration remainder: about 6.86 seconds;
- 403 manual subtitle cues, 10 canonical transcript chapters, 32 blocks;
- exact chapter-ID coverage: pass;
- exact block-ID coverage and order: pass;
- translated characters: 5,945 whole-chapter; 6,006 semantic-block;
- balanced blind positions: 5 chapters with whole-chapter as A, 5 as B;
- no audio/video artifacts and no publish action.

Compared with the user's earlier 14-minute-plus workflow, this two-candidate
experiment used 22.5% of 14 minutes: at least 4.44x faster, or at least 77.5%
less wall time. This is a directional comparison because the outputs differ.

## Checkpoint rerun

After adding checkpoints bound to source, strategy, model, prompt, and ordered
IDs, the same command completed in 6.99 seconds with both candidates reused and
zero model calls. The manifest keeps original generation timings separately from
the current checkpoint-hit timings.

## Human gate

No automatic winner is declared. `blind_review.md` contains the English source,
balanced A/B candidates, tie support, and the agreed optional rubric. The answer
key is stored separately and should remain unopened until human scoring ends.

## Final-text evaluation repair and recollection

Human feedback identified a shared target-text defect in the first experiment:
the source explicitly said `big omega` and `little omega`, while both candidates
retained plain `omega`. The new final-text gate reproduced the old failure before
the prompt repair:

- whole-chapter: expected `Ω`, `ω`; both missing;
- semantic-block: expected `Ω`, `ω`; both missing.

The repaired experiment keeps formula/LaTeX reconstruction disabled but requires
faithful normalization of explicitly named and cased symbols. Prompt SHA and
artifact schema changes invalidated both old checkpoints.

Fresh recollection results:

- wall time: 194.34 seconds;
- whole-chapter generation: 90.422 seconds;
- semantic-block generation: 93.890 seconds;
- 10 chapters and 32 blocks with exact ordered ID coverage;
- whole-chapter final text: 5,894 characters, `Ω` 27 times, `ω` 2 times,
  no plain `omega`;
- semantic-block final text: 5,810 characters, `Ω` 27 times, `ω` 2 times;
  two plain `omega` occurrences are parenthetical first-use labels;
- both candidates passed notation, coverage, and internal-ID leakage gates;
- `evaluation.json` status: `ready_for_human_review`;
- balanced blind positions: 5:5;
- no audio/video artifacts and no Obsidian files.

The fresh two-candidate run was 5.23 seconds slower than the earlier 189.11-second
run (2.8% wall-time overhead), while the two model generations increased only
2.06 seconds in total (1.1%). A final checkpoint rerun completed in 5.62 seconds
with zero model calls and retained the original generation timings.
