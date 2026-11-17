"""Resource sections contain plain solid lists and/or texture bundles only."""
import hashlib
from formats import require
import texanim


def convert_resources(roots, number, *, animation_inventory=None):
    """Keep caller identity; resource payloads have no scenery number to rewrite."""
    # Imported here so the section dispatcher can import this module directly.
    from convert import Builder, Stats, convert_list, convert_tpk, omit_animation_directory

    require(set(c.kind for c in roots) <= {0, 0x80134000, 0xb3300000, texanim.DIRECTORY},
            'undecoded resource section chunk')
    # Mixed resources keep source-owned identity even when a caller supplies a
    # different destination number. Texture-only sections can be byte-identical
    # in different slots, so their slot remains necessary to distinguish packs.
    identity = (int.from_bytes(hashlib.sha256(b''.join(c.encode() for c in roots)).digest()[:4], 'little')
                if any(c.kind == 0x80134000 for c in roots) else number)
    out, stats = Builder(0), Stats(pack_section=identity)
    for c in roots:
        if c.kind == 0:
            continue
        if c.kind == texanim.DIRECTORY:
            omit_animation_directory(c, stats, animation_inventory)
            continue
        out.pad(128)
        writer = convert_list if c.kind == 0x80134000 else convert_tpk
        out.data += writer(c, out.position, stats)
    require(stats.solids or stats.textures, 'section lacks resources')
    return bytes(out.data), stats
