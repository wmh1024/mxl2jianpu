"""Pipeline: MusicXML in, versioned jianpu PDFs out.

The workflow mirrors how this score was actually reviewed:

    diagnose   look for the defects an OMR export usually carries
    repair     fix what the diagnosis proved, and nothing else
    convert    render the plain jianpu and the jianpu+staff pair
    review     compare against an earlier version and mark the differences

Every stage is a function here, so a caller can run one stage or the whole
pipeline, and each stage's artefacts land in a version folder.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import compare, diagnose as diag, jianpu, musicxml as mx, render, repair
from .rests import rest_length

# a bar token that carries no duration
NO_TIME = {'(', ')', '~', '|', '[', ']', '{', '}', 'R{'}
PREFIX_BEATS = {'q': 0.5, 's': 0.25, 'd': 0.125, 'h': 0.0625}


def bar_total(tokens) -> float:
    """Length of one bar's tokens in quarter notes.

    Marks, slurs, dynamics and bar lines carry no time and are skipped. This is
    the same arithmetic jianpu-ly does when it checks that a bar is full, so a
    bar that passes here will not trip its barcheck.
    """
    import re
    total = 0.0
    for tok in tokens:
        if not tok or tok in NO_TIME or tok.startswith(('\\', '^', '_', 'Fr=', 'R*')):
            continue
        if re.match(r'^[A-Za-z]+$', tok) or re.match(r'^-?\d+=[A-G#b]+$', tok) \
                or re.match(r'^\d+/\d+$', tok):
            continue
        if tok == '-':
            total += 1.0
            continue
        rl = rest_length(tok)
        if rl is not None:
            total += rl
            continue
        pre = tok[0] if tok[:1] in PREFIX_BEATS else ''
        v = PREFIX_BEATS.get(pre, 1.0)
        if tok.endswith('.'):
            v *= 1.5
        total += v
    return round(total, 6)


@dataclass
class RepairPlan:
    """What to fix.  Defaults are safe for any file; the rest is score-specific."""
    fill_bars: bool = True
    flatten_voices: bool = True
    uniform_divisions: bool = True
    renumber: bool = True
    divisions: int = 96
    title: str | None = None
    composer: str | None = None
    part_name: str | None = None
    drop_tuplet_bars: list[str] = field(default_factory=list)
    time_changes: dict[str, tuple[int, int]] = field(default_factory=dict)


def apply_repairs(score, plan: RepairPlan, log: list[str]) -> None:
    """Mutate `score` according to `plan`, appending human-readable lines."""
    if plan.time_changes:
        part = score.find('part')
        if part is not None:
            for measure in part.findall('measure'):
                new = plan.time_changes.get(measure.get('number'))
                if not new:
                    continue
                attrs = measure.find('attributes')
                if attrs is None:
                    attrs = mx.ET.Element('attributes')
                    measure.insert(0, attrs)
                t = attrs.find('time')
                if t is None:
                    t = mx.ET.SubElement(attrs, 'time')
                for child in list(t):
                    t.remove(child)
                mx.ET.SubElement(t, 'beats').text = str(new[0])
                mx.ET.SubElement(t, 'beat-type').text = str(new[1])
            log.append(f'time signatures overridden on {len(plan.time_changes)} bars')

    # tuplets first: their compressed values would otherwise be padded bar by
    # bar before the spurious marking is removed
    if plan.drop_tuplet_bars:
        log.extend(repair.drop_tuplets(score, plan.drop_tuplet_bars))
    if plan.fill_bars:
        log.extend(repair.fill_bars(score))
    # flatten before padding: merging voices first means the padding step sees
    # the final single-voice bars, and no voice can be lost to an earlier pass
    if plan.flatten_voices:
        log.extend(repair.flatten_voices(score))
    if plan.fill_bars:
        log.extend(repair.fill_bars(score))
    if plan.uniform_divisions:
        log.extend(repair.uniform_divisions(score, plan.divisions))
    if plan.renumber:
        log.extend(repair.renumber(score))
    if plan.title or plan.composer or plan.part_name:
        log.extend(repair.set_metadata(score, plan.title, plan.composer, plan.part_name))


def render_version(score, out_dir: Path, stem: str,
                   octaves_before: bool = True) -> dict[str, Path]:
    """Write jianpu text, both .ly files and both PDFs into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    jianpu_ly = render.find_jianpu_ly()
    lilypond = render.find_lilypond()
    if jianpu_ly is None:
        raise RuntimeError('jianpu-ly.py not found; set MXL2JP_JIANPULY')
    if lilypond is None:
        raise RuntimeError('lilypond not found; set MXL2JP_LILYPOND')

    info = mx.describe(score)
    txt = jianpu.render_jianpu(
        score,
        title=info.get('title') or '',
        composer=info.get('composer') or '',
        instrument=(info.get('parts') or [''])[0],
        octaves_before=octaves_before,
    )
    txt_path = out_dir / f'{stem}.jianpu.txt'
    txt_path.write_text(txt, encoding='utf-8', newline='\n')

    made: dict[str, Path] = {'text': txt_path}

    for tag, with_staff in (('jianpu', False), ('staff', True)):
        src = txt_path
        if with_staff:
            lines = txt.splitlines()
            staff_lines = []
            for ln in lines:
                staff_lines.append(ln)
                if ln.strip() == 'OctavesBefore':
                    staff_lines.append('WithStaff')
            src = out_dir / f'{stem}.staff.txt'
            src.write_text('\n'.join(staff_lines) + '\n', encoding='utf-8', newline='\n')

        ly = out_dir / f'{stem}.{tag}.ly'
        ok, msg = render.run_jianpu_ly(jianpu_ly, src, ly)
        if not ok:
            raise RuntimeError(f'jianpu-ly failed for {tag}: {msg[:400]}')
        made[f'{tag}_ly'] = ly

        stem_pdf = out_dir / f'{stem}.{tag}'
        ok, msg = render.run_lilypond(lilypond, ly, stem_pdf)
        if not ok:
            raise RuntimeError(f'LilyPond failed for {tag}: {msg[-800:]}')
        made[f'{tag}_pdf'] = stem_pdf.with_name(stem_pdf.name + '.pdf')

    return made


def diagnose_file(mxl: Path) -> tuple[list, dict]:
    return diag.diagnose(mxl)


def _find_jianpu_text(folder: Path) -> Path | None:
    """The jianpu input file of a version folder.

    Accepts both the build naming (`<stem>.jianpu.txt`) and the published
    naming (`<piece>-V<n>-简谱源.txt`), so a version folder can come from
    either stage.
    """
    for pattern in ('*.jianpu.txt', '*简谱源.txt', '*.txt'):
        hit = sorted(folder.glob(pattern))
        if hit:
            return hit[0]
    return None


def build_review(version_dir: Path, previous_dir: Path, out_dir: Path,
                 label: str = '已修正') -> dict[str, object]:
    """Compare two published versions and write the marked PDFs."""
    cur_txt = _find_jianpu_text(version_dir)
    prev_txt = _find_jianpu_text(previous_dir)
    if cur_txt is None or prev_txt is None:
        raise RuntimeError(
            f'no jianpu source found in {version_dir if cur_txt is None else previous_dir}')

    bars = compare.changed_bars(prev_txt, cur_txt)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'changed_bars.txt').write_text(
        compare.summary_line(bars) + '\n', encoding='utf-8', newline='\n')

    result: dict[str, object] = {'bars': bars, 'count': len(bars), 'pdfs': {}}
    if not bars:
        return result

    lilypond = render.find_lilypond()
    for tag in ('jianpu', 'staff'):
        # accept both build naming and published naming for the .ly source
        patterns = (f'*.{tag}.ly', '*简谱.ly' if tag == 'jianpu' else '*对照版.ly')
        src_ly = None
        for pat in patterns:
            hit = sorted(version_dir.glob(pat))
            if hit:
                src_ly = hit[0]
                break
        if src_ly is None:
            continue
        marked = out_dir / f'{tag}.marked.ly'
        compare.annotate(src_ly, marked, bars, label)
        stem = out_dir / f'{tag}.marked'
        ok, msg = render.run_lilypond(lilypond, marked, stem)
        if ok:
            result['pdfs'][tag] = stem.with_name(stem.name + '.pdf')
    return result
