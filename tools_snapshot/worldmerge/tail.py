"""Additional sky declaration; the streamed animation directory is undecoded.

The source declaration builder at 006d5c10 and target builder at 0072f030
emit identical elements for source effect 19 and target effect 15. Both use
position FLOAT3, normal FLOAT3, D3DCOLOR, TEXCOORD0 FLOAT2, TEXCOORD1 FLOAT2.
These are extra tables only: the section writer installs its own dispatch.
"""
import math
import struct

from formats import require


EFFECTS = {19: (44, 15, 44)}
TARGET_STRIDES = {15: 44}

# D3DVERTEXELEMENT9: stream, offset, type, method, usage, usage index.
# The declaration terminator is not a vertex element and consumes no bytes.
SKY_DECLARATION = (
    (0, 0, 2, 0, 0, 0),
    (0, 12, 2, 0, 3, 0),
    (0, 24, 4, 0, 10, 0),
    (0, 28, 1, 0, 5, 0),
    (0, 36, 1, 0, 5, 1),
)


def convert_vertices(raw, effect, count):
    """Preserve every sky element, refusing a mismatched extent or bad float."""
    require(effect == 19, f'undecoded tail source effect {effect}')
    require(isinstance(count, int) and count >= 0, 'sky vertex count')
    require(len(raw) == 44 * count, 'sky source vertex count/stride mismatch')
    for vertex in struct.iter_unpack('<6fI4f', raw):
        require(all(math.isfinite(v) for v in (*vertex[:6], *vertex[7:])),
                'non-finite sky vertex')
    return bytes(raw)
