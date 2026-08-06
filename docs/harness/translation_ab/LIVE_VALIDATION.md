# Live Validation

## Input

- Course: Probability Bootcamp
- Lesson 4: Set Theory in Probability: Sample Spaces and Events
- Video ID: `b_ev4Hdzh-U`
- Duration: 24:12
- Backend/model: `codex_cli:gpt-5.4`

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

After adding source-fingerprinted candidate checkpoints, the same command
completed in 5.88 seconds with both candidates reused and zero model calls.
The manifest keeps original generation timings separately from the current
checkpoint-hit timings.

## Human gate

No automatic winner is declared. `blind_review.md` contains the English source,
balanced A/B candidates, tie support, and the agreed optional rubric. The answer
key is stored separately and should remain unopened until human scoring ends.
