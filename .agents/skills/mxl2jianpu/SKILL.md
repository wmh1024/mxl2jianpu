---
name: mxl2jianpu
description: Turn a printed score PDF plus its OCR'd MusicXML (.mxl/.musicxml) into a jianpu (numbered notation) PDF and a jianpu+staff PDF, using a vision model to reconcile the OCR against the printed page before anything is converted. Use when asked to 排版/渲染 简谱, convert MusicXML to 简谱, check an OMR export, or produce a red-marked comparison between two versions; the tools live in mxl2jianpu/.
---

# From printed score to 简谱, with the page as the authority

You are given two files that describe the same music:

- a **PDF of the printed score** — the authority;
- an **`.mxl` / `.musicxml` export from OCR software** — a machine's reading of
  it, which is wrong in places.

Your job is a jianpu PDF and a jianpu+staff PDF that match the printed page, and
a record of every place you had to overrule the OCR and why.

**This task requires a vision model.** You must look at the page. Every
correction is justified by what you saw, not by what the XML implies. If you
cannot see images in this session, stop and say so — a text-only pass will
produce a confident, wrong score.

## The rule that governs everything

> Change nothing the printed page does not show. Add nothing you cannot point
> at.

OCR output is not a draft to improve on; it is evidence to be checked. When the
XML and the page disagree, the page wins. When you cannot read the page clearly
enough to decide, the answer is "unresolved", not a plausible guess.

The tools enforce this: `--evidence TYPE=BARS=PAGE=WHAT` is required for every
override, and the command refuses to run without it. That is deliberate. Do not
work around it — if you cannot fill in `WHAT`, you have not looked.

## Order of work

### 1. Look at the score first

```powershell
python mxl2jianpu/run.py pages score.pdf -o look --dpi 200
```

Look at the images before running anything else. You are learning what the
music is: how many systems, where the metre changes, whether there are repeats,
what the instrument is, how the title is set. Read the cropped regions when
detail matters:

```powershell
python mxl2jianpu/run.py crop score.pdf -p 2 --box 0.05,0.42,0.55,0.52 -o look/p2-m17.png
```

`--box` is `x0,y0,x1,y1` as fractions of the page from the top-left. A `--zoom`
of 3 or more makes accidentals and dots legible.

### 2. Ask the tool what is wrong

```powershell
python mxl2jianpu/run.py diagnose score.mxl
```

This reports facts about the file: bars whose voices do not fill the metre,
`<duration>` contradicting `<type>`, `<divisions>` changing mid-piece, duplicate
measure numbers. Those are the places OCR is likely to have misread — but they
are a list of *questions*, not answers.

```powershell
python mxl2jianpu/run.py review-bars score.mxl
```

groups the suspect bars by how far off they are. A large group that is short by
exactly one beat usually means the metre was misread for that whole section,
not that many separate rests went missing. Confirm that on the page.

### 3. Reconcile, bar by bar, against the page

For each group of suspect bars:

1. Crop that part of the page and look at it.
2. Decide what the printed music actually says.
3. If the OCR is wrong, plan an override with the evidence.

Common findings and what they look like on the page:

| What the tool says | What to look for | Override |
|---|---|---|
| A run of bars short by the same amount | a time signature the OCR missed | `--time-change 89=6/8` |
| A bar whose notes form 6 equal groups | a tuplet bracket the OCR invented, or one it missed | `--drop-tuplets 136` |
| One bar overfull by a beat | a note the OCR split in two, or a dotted value misread | `--drop-tuplets`, or leave it and report it |
| Bars with more voices than the page shows | a chord the OCR heard as two voices | usually nothing — the merge handles it |

Do not batch-guess. If you cannot read a bar, say which bar and why.

### 4. Repair, with evidence attached

```powershell
python mxl2jianpu/run.py build score.mxl -o out --stem 曲名 `
    --title 乐作欢歌 --composer 吴耀 --part 中阮 `
    --time-change 89=6/8 --evidence "time-signature=89-140=2=printed 6/8 at bar 89, 4/4 resumes at 141" `
    --drop-tuplets 136 --evidence "tuplet=136=3=six plain eighths under a 6/8, no bracket"
```

Every override needs a matching `--evidence`. The command writes `changes.json`
next to the output recording each edit with page and observation.

The metadata (`--title`, `--composer`, `--part`) also comes from the page — read
the header block, do not invent it. If the page has no title, leave it empty
rather than naming the file after the score.

### 5. Verify, and believe the numbers

```powershell
python mxl2jianpu/run.py build ...          # prints the bar check when it finishes
python scripts\check_bars.py out\曲名.musicxml
python scripts\verify_pitches.py score.mxl out\曲名.musicxml
```

Two independent things must hold:

- **every bar fills its metre** (`bars off: 0`);
- **every bar kept the same pitches** (`every bar has the same pitches`).

They fail differently, and both matter. A score can have perfect bar lengths
and still lose a note when voices were merged — the staff drops it, the 简谱
shows nothing wrong, and only the pitch check notices.

`scripts/smoke_test.py` proves the render chain works without needing a score
file (`SMOKE PASS`); run it after changing tool code or when the environment
is in doubt.

### 6. Look at the result, next to the original

Open `out/曲名.staff.pdf` and the source PDF and compare them page by page.
Check:

- every metre change is in the right place;
- the octave dots point the same way as the printed register;
- chords and double stops survived;
- the title block reads as printed.

This step is not optional and not ceremonial: an octave-wide error in a
transposed passage is invisible in text and obvious in two pages side by side.

### 7. If a previous version exists, mark what changed

```powershell
python mxl2jianpu/run.py review out_v2 out_v1 -o diff --label 已修正
```

Changed bars get red notes, thick red bar lines and a boxed caption. Use
`notes_only` comparison when the question is "did I change any notes", and the
full comparison when the question is "which bars did this revision touch".

## What the tool will not do, and why

- **It will not guess a metre.** A file that misreads 6/8 as 4/4 is internally
  consistent; no inspection of the file reveals it. Only the page does.
- **It will not fill in a title.** Missing metadata means missing on the page.
- **It will not silently merge voices.** A note of an inner voice becomes a
  chord tone so the pitch survives; dropping it would corrupt the staff.
- **It refuses unevidenced overrides.** That refusal is the safety property of
  this whole workflow, not an inconvenience to route around.

## Octaves: the one rule that is easy to get backwards

jianpu-ly realises `1=X` as `\transpose c X` from a bare `c` (C3). An unmarked
figure therefore sounds X3 when X is G, A or B, but X4 when X is C, D, E or F.
`jianpu.to_jianpu` applies this, which is why the same pitch is `6` in a G-major
passage and `6,` in a D-major one. Getting it wrong shifts a whole passage by an
octave while every note keeps its name — visible only by comparing pages.

## When the conversion fails

jianpu-ly reports `note crosses barline` and names a bar that looks right on its
own. The real fault is an earlier bar that is short or long:

```powershell
python scripts\find_bad_bar.py out\曲名.jianpu.txt
```

It bisects the input and reports the first prefix that fails.

## Before you report done

State these, from the actual output:

- bars off: must be 0;
- pitch differences: must be 0;
- how many overrides, and that each has an evidence line in `changes.json`;
- anything you could not resolve, named bar by bar.

If you could not look at the pages, say that instead. A score you did not check
against the print is not finished, however good the PDF looks.
