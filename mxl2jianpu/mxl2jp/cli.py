"""Command line for mxl2jianpu.

    diagnose <score>                     report OMR defects
    pages    <pdf> -o <dir>              render the printed pages for looking at
    crop     <pdf> -p N --box ...        crop one region, enlarged
    review-bars <score> --expect ...     which bars disagree with the metre
    repair   <score> -o <out> [...]      apply repairs
    convert  <score> -o <dir> --stem X   render jianpu and jianpu+staff PDFs
    review   <new_dir> <old_dir> -o <d>  mark the differences between versions
    build    <score> -o <out> [...]      diagnose, repair, convert in one go
    tools                                show the external tools found
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (audit, compare, diagnose, jianpu, musicxml as mx, pages,
               pipeline, render, repair)


def cmd_diagnose(args) -> int:
    findings, summary = diagnose.diagnose(args.score)
    print(diagnose.report(args.score))
    if args.json:
        Path(args.json).write_text(
            json.dumps({'summary': summary,
                        'findings': [f.__dict__ for f in findings]},
                       ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\nwrote {args.json}')
    return 0 if not any(f.severity == 'error' for f in findings) else 1


def cmd_pages(args) -> int:
    try:
        out = pages.render_pages(args.pdf, args.output, dpi=args.dpi,
                                 pages=args.pages, prefix=args.prefix)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    for p in out:
        print(p)
    print(f'\nrendered {len(out)} page(s) at {args.dpi} dpi')
    print('Look at these images before deciding anything about the score: '
          'the printed page is the authority, not the MusicXML.')
    return 0


def cmd_crop(args) -> int:
    box = tuple(float(x) for x in args.box.split(','))
    if len(box) != 4:
        raise SystemExit('--box wants x0,y0,x1,y1 as fractions of the page')
    try:
        out = pages.crop_region(args.pdf, args.page, box, args.output,
                                zoom=args.zoom)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(out)
    return 0


def cmd_review_bars(args) -> int:
    """List the bars whose length disagrees with the metre, with the delta."""
    findings, _ = diagnose.diagnose(args.score)
    bars = [f for f in findings if f.kind == 'bar-length']
    if not bars:
        print('every bar fills its time signature; nothing to reconcile.')
        return 0
    groups: dict[str, list[str]] = {}
    for f in bars:
        groups.setdefault(f.detail, []).append(f.bar)
    print(f'{len(bars)} bars do not fill their metre.\n')
    for detail, nums in groups.items():
        print(f'  {detail}')
        print(f'    bars: {", ".join(nums[:20])}'
              + (' ...' if len(nums) > 20 else ''))
    print('\nFor each group, look at those bars on the printed page and decide '
          'what the metre actually is. Do not guess from the MusicXML alone.')
    if args.json:
        Path(args.json).write_text(
            json.dumps([{'bar': f.bar, 'detail': f.detail} for f in bars],
                       ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\nwrote {args.json}')
    return 1



def _plan_from_args(args) -> pipeline.RepairPlan:
    changes = {}
    for item in args.time_change or []:
        bar, sig = item.split('=', 1)
        a, b = sig.split('/')
        changes[bar] = (int(a), int(b))
    return pipeline.RepairPlan(
        fill_bars=not args.no_fill,
        flatten_voices=not args.no_flatten,
        uniform_divisions=not args.no_uniform,
        renumber=not args.no_renumber,
        divisions=args.divisions,
        title=args.title,
        composer=args.composer,
        part_name=args.part,
        drop_tuplet_bars=(args.drop_tuplets or '').split(',') if args.drop_tuplets else [],
        time_changes=changes,
    )


def _log_from_args(args, out_dir: Path | None) -> audit.ChangeLog:
    """Build the change log from --evidence entries and write it beside the output.

    `--evidence TYPE=BARS=PAGE=WHAT` is how the agent states that it looked at
    the page. An entry without a readable `WHAT` is refused, which is the point:
    it stops the model from editing on the strength of the MusicXML alone.
    """
    log = audit.ChangeLog()
    for raw in args.evidence or []:
        parts = raw.split('=', 3)
        if len(parts) < 4:
            raise SystemExit(
                f'bad --evidence {raw!r}; want TYPE=BARS=PAGE=WHAT THE PAGE SHOWS')
        kind, bars, page, seen = parts
        log.add(kind=kind, bars=audit.parse_bar_spec(bars),
                page=int(page), seen=seen)

    # Every override must be evidenced. A time signature applies from its start
    # bar onward, so only that start bar needs to appear in an evidence line;
    # `--drop-tuplets` bars each need one.
    start_bars: list[str] = []
    for item in args.time_change or []:
        bar = item.split('=', 1)[0]
        start_bars.append(audit.parse_bar_spec(bar)[0])
    if args.drop_tuplets:
        start_bars.extend(audit.parse_bar_spec(args.drop_tuplets))

    evidenced = log.bars_touched()
    missing = [b for b in start_bars if b not in evidenced]
    if missing:
        raise SystemExit(
            'these overrides have no --evidence entry: ' + ', '.join(missing[:12])
            + '\nAdd --evidence TYPE=BARS=PAGE=WHAT, describing what the printed '
              'page shows. A change without evidence is a guess.')

    if out_dir is not None and len(log):
        path = log.to_json(out_dir / 'changes.json')
        print(f'change log -> {path}')
    return log


def cmd_repair(args) -> int:
    score = mx.read_score(args.score)
    plan = _plan_from_args(args)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    _log_from_args(args, out.parent)
    log: list[str] = []
    pipeline.apply_repairs(score, plan, log)
    repair.save(score, out)
    print('\n'.join(log))
    print(f'\nwrote {out}')
    return 0


def cmd_convert(args) -> int:
    score = mx.read_score(args.score)
    made = pipeline.render_version(score, Path(args.output), args.stem)
    for k, v in made.items():
        print(f'{k:<12} {v}')
    return 0


def cmd_review(args) -> int:
    result = pipeline.build_review(Path(args.new), Path(args.old),
                                   Path(args.output), args.label)
    print(f'changed bars: {result["count"]}')
    if result['count']:
        print('  ' + compare.summary_line(result['bars']))
    for tag, pdf in result['pdfs'].items():
        print(f'  {tag:<8} {pdf}')
    return 0


def cmd_build(args) -> int:
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    findings, summary = diagnose.diagnose(args.score)
    errors = sum(1 for f in findings if f.severity == 'error')
    print(f'diagnose: {len(findings)} findings, {errors} errors')
    if args.verbose:
        print(diagnose.report(args.score))

    _log_from_args(args, out)

    score = mx.read_score(args.score)
    plan = _plan_from_args(args)
    log: list[str] = []
    pipeline.apply_repairs(score, plan, log)
    if args.verbose:
        print('\n'.join(log))

    fixed = out / f'{args.stem}.musicxml'
    repair.save(score, fixed)
    print(f'repaired -> {fixed}')

    made = pipeline.render_version(score, out, args.stem)
    for k, v in made.items():
        print(f'{k:<12} {v}')

    # a conversion is only trustworthy when the bar check passes; report it
    # here so nobody has to remember to run the script separately
    bars = jianpu.bars_to_jianpu(score)
    off = [b.number for b in bars
           if abs(pipeline.bar_total(b.tokens) - b.target) > 1e-6]
    if off:
        print(f'\nWARNING: {len(off)} bar(s) do not fill the metre: {off[:8]}')
        print('Do not deliver this PDF. Run scripts/check_bars.py and fix first.')
    else:
        print(f'\nbar check: all {len(bars)} bars fill their time signature.')
    return 0 if not off else 1


def cmd_tools(args) -> int:
    print(f'lilypond : {render.find_lilypond()}')
    print(f'jianpu-ly: {render.find_jianpu_ly()}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='mxl2jianpu', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)

    d = sub.add_parser('diagnose', help='report OMR defects in a MusicXML file')
    d.add_argument('score')
    d.add_argument('--json', help='also write the findings as JSON')
    d.set_defaults(func=cmd_diagnose)

    pg = sub.add_parser('pages',
                        help='render the printed PDF pages as images to look at')
    pg.add_argument('pdf', help='the source printed score')
    pg.add_argument('-o', '--output', required=True, help='folder for the PNGs')
    pg.add_argument('--dpi', type=int, default=150,
                    help='resolution; 200+ for reading accidentals (default 150)')
    pg.add_argument('--pages', default='all',
                    help="'all', a page number, or a range like '2-4'")
    pg.add_argument('--prefix', help='filename prefix (default: the pdf name)')
    pg.set_defaults(func=cmd_pages)

    cp = sub.add_parser('crop', help='crop one region of a page, enlarged')
    cp.add_argument('pdf')
    cp.add_argument('-p', '--page', type=int, required=True)
    cp.add_argument('--box', required=True,
                    help='x0,y0,x1,y1 as fractions of the page, from top-left')
    cp.add_argument('-o', '--output', required=True)
    cp.add_argument('--zoom', type=float, default=3.0)
    cp.set_defaults(func=cmd_crop)

    rb = sub.add_parser('review-bars',
                        help='list bars that disagree with the metre, by reason')
    rb.add_argument('score')
    rb.add_argument('--json')
    rb.set_defaults(func=cmd_review_bars)

    def add_plan_args(sp):
        sp.add_argument('--divisions', type=int, default=96,
                        help='division grid for uniform rewrite (default 96)')
        sp.add_argument('--title')
        sp.add_argument('--composer')
        sp.add_argument('--part', dest='part', help='part name to write')
        sp.add_argument('--drop-tuplets', help='comma separated bar numbers')
        sp.add_argument('--time-change', action='append',
                        help='BAR=beats/beat-type, repeatable')
        sp.add_argument('--evidence', action='append',
                        help='TYPE=BARS=PAGE=WHAT THE PAGE SHOWS; repeatable. '
                             'Required for every deviation from the OMR output.')
        sp.add_argument('--no-fill', action='store_true', help='do not pad bars')
        sp.add_argument('--no-flatten', action='store_true',
                        help='do not merge extra voices')
        sp.add_argument('--no-uniform', action='store_true')
        sp.add_argument('--no-renumber', action='store_true')

    r = sub.add_parser('repair', help='apply repairs and write a MusicXML file')
    r.add_argument('score')
    r.add_argument('-o', '--output', required=True)
    add_plan_args(r)
    r.set_defaults(func=cmd_repair)

    c = sub.add_parser('convert', help='render jianpu and jianpu+staff PDFs')
    c.add_argument('score')
    c.add_argument('-o', '--output', required=True)
    c.add_argument('--stem', default='score')
    c.set_defaults(func=cmd_convert)

    v = sub.add_parser('review', help='mark the differences between two versions')
    v.add_argument('new', help='folder of the newer version')
    v.add_argument('old', help='folder of the older version')
    v.add_argument('-o', '--output', required=True)
    v.add_argument('--label', default='已修正')
    v.set_defaults(func=cmd_review)

    b = sub.add_parser('build', help='diagnose, repair and convert in one run')
    b.add_argument('score')
    b.add_argument('-o', '--output', required=True)
    b.add_argument('--stem', default='score')
    b.add_argument('-v', '--verbose', action='store_true')
    add_plan_args(b)
    b.set_defaults(func=cmd_build)

    t = sub.add_parser('tools', help='show which external tools were found')
    t.set_defaults(func=cmd_tools)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
