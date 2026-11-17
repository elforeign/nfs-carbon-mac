"""Private CLI: in-memory proof or staged archives outside the source trees."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from formats import FormatError, TrackIndex, free_number, require
from convert import convert_section
from validate import validate_section, validate_translation


PARENT = HERE.parents[2]
DEFAULT_MW = PARENT / 'Need For Speed Most Wanted Black Edition' / 'TRACKS'
DEFAULT_CARBON = PARENT / 'inputs' / 'NFSC' / 'TRACKS'
OUTPUT_ROOT = PARENT / '.runs' / 'worldmerge'


def load_index(root, base):
    path = Path(root) / f'{base}.BUN'
    require(path.stat().st_size <= 8 << 20, 'track index exceeds size budget')
    raw = path.read_bytes()
    index = TrackIndex(raw)
    stream = Path(root) / f'STREAM{base}.BUN'
    index.validate(stream.stat().st_size)
    require(index.encode() == raw, 'original index did not round-trip byte-exact')
    return index, stream, raw


def read_section(stream, section):
    size = stream.stat().st_size
    require(0 < section.size <= 256 << 20, 'section read exceeds size budget')
    require(section.offset <= size and section.size <= size - section.offset, 'section read outside stream')
    with stream.open('rb') as f:
        f.seek(section.offset)
        raw = f.read(section.size)
    require(len(raw) == section.size, 'short stream-section read')
    return raw


def negative_controls(index_data, stream_size):
    rejected = []
    for name in ('duplicate_number', 'offset_past_end'):
        index = TrackIndex(index_data)
        record = bytearray(index.sections[-1].raw)
        if name == 'duplicate_number':
            struct.pack_into('<h', record, 8, index.sections[0].number)
        else:
            struct.pack_into('<I', record, 20, stream_size + 2048)
        from formats import Section
        index.sections[-1] = Section(bytes(record))
        try:
            TrackIndex(index.encode()).validate(stream_size)
        except FormatError:
            rejected.append(name)
        else:
            raise FormatError(f'broken index passed: {name}')
    return rejected


def prepare(mw_root=DEFAULT_MW, carbon_root=DEFAULT_CARBON, section_number=1904):
    source, source_stream, source_bytes = load_index(mw_root, 'L2RA')
    target, target_stream, target_bytes = load_index(carbon_root, 'L5RA')
    record = next((s for s in source.sections if s.number == section_number), None)
    require(record is not None and record.scenery, 'source scenery section absent')
    number = free_number(source, target)
    boundary = next((b for b in source.boundaries() if b.number == section_number), None)
    require(boundary is not None, 'source section boundary absent')
    shift = 20000
    translated = boundary.translate(number, shift)
    translated.validate()
    source_section = read_section(source_stream, record)
    # The 20,000 m shift predates the 4,096 m precull period rule.
    generated, stats = convert_section(source_section, number, shift, source_number=record.number,
                                       allow_precull_mismatch=True)
    counts, deps = validate_section(generated, number)
    spatial = validate_translation(source_section, generated, shift,
                                   source_number=record.number, target_number=number)
    size = target_stream.stat().st_size
    padding = -size % 2048
    appended = record.replace(number=number, offset=size + padding, size=len(generated), shift_x=shift)
    target.sections.append(appended)
    target.add_visibility(translated)
    merged = target.encode()
    reread = TrackIndex(merged)
    stream_size = size + padding + len(generated)
    reread.validate(stream_size)
    require(reread.encode() == merged, 'merged index did not round-trip')
    before = TrackIndex(target_bytes)
    require([s.raw for s in reread.sections[:-1]] == [s.raw for s in before.sections],
            'existing target section records changed')
    boundaries = list(reread.boundaries())
    require(len({b.number for b in boundaries}) == len(boundaries), 'duplicate visibility number')
    require([b.raw for b in boundaries[:-1]] == [b.raw for b in before.boundaries()],
            'existing target boundaries changed')
    lo_x, lo_y, hi_x, hi_y = translated.bounds
    x, y, _ = appended.position
    require(lo_x <= x <= hi_x and lo_y <= y <= hi_y, 'new section center outside translated boundary')
    rejected = negative_controls(merged, stream_size)
    used_source = {s.number for s in source.sections if s.scenery}
    used_target = {s.number for s in before.sections if s.scenery}
    report = {
        'status': 'offline structure validated; rendering/collision not proved',
        'source_section': record.name, 'source_number': record.number,
        'target_section': appended.name, 'target_number': number,
        'reserved_lod_number': number + 40,
        'axis': 'render/world first coordinate X; horizontal XY plane, vertical Z',
        'shift_m': [shift, 0, 0],
        'physics_translation_note': 'render (X,Y,Z) corresponds to physics (-Y,Z,X); translate physics Z by +20000',
        'source_center_xy': record.position[:2], 'target_center_xy': appended.position[:2],
        'preserved_record_field_48': record.position[2],
        'source_boundary': boundary.bounds, 'target_boundary': translated.bounds,
        'source_section_bytes': record.size, 'target_section_bytes': len(generated),
        'original_stream_bytes': size, 'merged_stream_bytes': stream_size,
        'append_offset': appended.offset, 'append_padding': padding,
        'original_index_bytes': len(target_bytes), 'merged_index_bytes': len(merged),
        'records': {'source': len(source.sections), 'target': len(before.sections), 'merged': len(reread.sections)},
        'original_roundtrips': {'source': True, 'target': True},
        'scenery_numbers': {'source': len(used_source), 'target': len(used_target),
                            'assignments': len(used_source) + len(used_target),
                            'collisions': len(used_source & used_target), 'distinct': len(used_source | used_target)},
        'counts': counts, 'spatial_validation': spatial,
        'conversion': {k: dict(v) if hasattr(v, 'items') else v
                                        for k, v in vars(stats).items()},
        'external_dependencies': deps,
        'negative_controls_rejected': rejected,
        'index_sha256': hashlib.sha256(merged).hexdigest(),
        'section_sha256': hashlib.sha256(generated).hexdigest(),
        'source_index_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'target_index_sha256': hashlib.sha256(target_bytes).hexdigest(),
    }
    return merged, generated, target_stream, report


def check_output(out, sources):
    out = Path(out).expanduser().absolute()
    # The designated output tree is fixed. Resolving it may not authorize a
    # symlink to an installation, another checkout, or another directory.
    lexical = OUTPUT_ROOT.absolute()
    expected = lexical.parent.resolve() / lexical.name
    require(out.is_relative_to(lexical), 'output must be under the designated worldmerge run directory')
    require(out.resolve().is_relative_to(expected), 'output symlink escapes designated run directory')
    require(out != lexical, 'use a new child directory for atomic output publication')
    for source in sources:
        root = Path(source).resolve()
        require(not out.resolve().is_relative_to(root), 'output is inside a source tree')
    require(not out.exists() and not out.is_symlink(), 'output already exists; choose a new child directory')
    return out


def write_outputs(out, index, section, stream, report, sources):
    out = check_output(out, sources)
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.worldmerge-stage-', dir=out.parent))
    try:
        original_stat = stream.stat()
        tracks = stage / 'TRACKS'
        tracks.mkdir()
        (tracks / 'L5RA.BUN').write_bytes(index)
        digest = hashlib.sha256()
        with stream.open('rb') as src, (tracks / 'STREAML5RA.BUN').open('xb') as dst:
            while block := src.read(8 << 20):
                digest.update(block)
                dst.write(block)
            gap = bytes(report['append_padding'])
            dst.write(gap)
            dst.write(section)
            digest.update(gap)
            digest.update(section)
            dst.flush()
            os.fsync(dst.fileno())
        after = stream.stat()
        require((original_stat.st_dev, original_stat.st_ino, original_stat.st_size, original_stat.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'source stream changed during copy')
        written = tracks / 'STREAML5RA.BUN'
        require(written.stat().st_size == report['merged_stream_bytes'], 'written stream size differs')
        TrackIndex((tracks / 'L5RA.BUN').read_bytes()).validate(written.stat().st_size)
        report = dict(report, stream_sha256=digest.hexdigest())
        (stage / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
        # Recheck the destination before publishing a complete directory.
        check_output(out, sources)
        os.rename(stage, out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--section', type=int, default=1904)
    parser.add_argument('--check-only', action='store_true', help='validate entirely in memory, without artifact writes')
    parser.add_argument('--out', type=Path, default=OUTPUT_ROOT / 'S04-B27')
    args = parser.parse_args()
    try:
        merged, generated, stream, report = prepare(args.mw, args.carbon, args.section)
        if args.check_only:
            print(json.dumps(report, indent=2))
        else:
            out = write_outputs(args.out, merged, generated, stream, report, (args.mw.parent, args.carbon.parent, HERE.parents[1]))
            print(f'PASS: wrote {out}; {len(merged)} index bytes; {report["merged_stream_bytes"]} stream bytes')
    except (OSError, FormatError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
