"""Recreate the world hook manifest from a supported executable, offline.

Only addresses, state offsets and the supported image hash are stored here.
All sixteen 32-byte witnesses are read from the image and written below out/.
This does not recreate profiles, screen drivers or region geometry proofs.
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output, image_functions
from recomp import PE

IMAGE_SHA256 = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
FUNCTIONS = HERE / 'functions_nfsc.tsv'
HOOK_ADDRESSES = {
    'select': 0x006bbdf0, 'request': 0x0079e8f0, 'complete': 0x0079e670,
    'camera': 0x004822f0, 'position': 0x0079a0b0, 'predict': 0x0079a170,
    'stream_ready': 0x007a27f0, 'section_pick': 0x007a4900,
    'scenery_tree': 0x0079fdb0, 'scenery_draw': 0x0079fa60,
    'model_submit': 0x00729320, 'mesh_add': 0x00727930,
    'prop_factory': 0x006da120, 'prop_spawn': 0x00817940,
    'prop_position': 0x006c6ff0, 'prop_tick': 0x006d98d0,
}


def world_manifest(image, functions=FUNCTIONS):
    """Reproduce the lifecycle/draw diagnostics' complete manifest, with no cache."""
    pe = PE(str(image), expected_sha256=IMAGE_SHA256)
    # Native rigid-body readers also occur as data-referenced vtable entries.
    starts = {a for a, _, _ in image_functions(pe, functions, data_starts=True)}
    for name, address in HOOK_ADDRESSES.items():
        if address not in starts:
            raise ValueError(f'world hook function missing: {name} FUN_{address:08X}')
    manifest = {
        'sha256': IMAGE_SHA256, 'prefix': 'NFSC',
        'track_global': 0x00a7a1a8, 'descriptor_global': 0x00b69ba0,
        'track_offset': 0x8a, 'texture_sentinel_global': 0x00b1d810,
        'mesh_count_global': 0x00ab0bf0,
        'hooks': {name: {'address': address, 'bytes': pe.read(address, 32).hex()}
                  for name, address in HOOK_ADDRESSES.items()},
    }
    from private_world import validate_manifest
    return validate_manifest(manifest, Path(image))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--exe', required=True, type=Path)
    ap.add_argument('--functions', type=Path, default=FUNCTIONS)
    ap.add_argument('--out', type=Path, default=HERE / 'out/moon3-scratch')
    args = ap.parse_args()
    manifest = world_manifest(args.exe, args.functions)
    out = ignored_output(args.out)
    (out / 'world_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'RECREATE PASS hooks={len(manifest["hooks"])} manifest={out / "world_manifest.json"}')


if __name__ == '__main__':
    main()
