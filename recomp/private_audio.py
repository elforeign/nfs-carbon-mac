"""Witnessed private DAC wrappers and optional positional hook byte identities."""
import hashlib
import re
from private_render import function_span

CARBON_SHA256 = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
WITNESSES = (
    (0x008A74DD, 0x208, '27b5cecc877e11c3b812c35f75ede33a532fb188927da6edf0bfa49a56df98d9'),
    (0x008B074C, 0x101, '1a22f0e719bbe18f8d0e9d875538c08f4faa5122de64ef6502535b82240224bf'),
)
# Positional providers live in the hook registry; keep limiter instrumentation
# separate so existing DAC fixtures retain their original completeness set.
POS_WITNESSES = (
    (0x008A4C63, 0x4f, '4b43010db13d95b3f35fff5ae2825567915628ccc10f2d0ef8bcef1706acd275'),
    (0x008A4CC8, 0x9b, '348649b3fe2268a911ab7fb7ff7989f4eebf6052df246c0b64e1c755bcd69bc3'),
    (0x0089E2FE, 0x51, '78f91ec8a0a2420a0bd126af5d36fb72d61c9e7fdfc47eff7d6d4031576d2566'),
)
HOOKS = {a for a, _, _ in WITNESSES}


def validate(image):
    if image['sha256'] != CARBON_SHA256:
        return
    from recomp import PE
    pe = PE(image['exe'], expected_sha256=CARBON_SHA256)
    for address, size, digest in WITNESSES + POS_WITNESSES:
        if hashlib.sha256(pe.read(address, size)).hexdigest() != digest:
            raise ValueError(f'private audio witness differs: {address:08X}')


def instrument(source, sha256):
    if sha256 != CARBON_SHA256:
        return source, []
    found = []
    for address in sorted(HOOKS):
        symbol = f'f_{address:08X}'
        if not re.search(r'void ' + symbol + r'\(', source):
            continue
        begin, end = function_span(source, symbol)
        declaration = source.rfind('void ', 0, begin)
        original = source[declaration:end].replace(symbol + '(', symbol + '_audio_original(', 1)
        if address == 0x008A74DD:
            work = f'''uint64_t saved = private_carbon_audio_enter(c->ecx);
    {symbol}_audio_original(c);
    private_carbon_audio_leave(saved);'''
        else:
            work = f'''uint8_t *const G = guest_base();
    private_carbon_audio_before(M32(c->esp), M32(c->esp+4), M32(c->esp+16));
    {symbol}_audio_original(c);'''
        source = source[:declaration] + original + f'\nvoid {symbol}(Cpu *c) {{\n    {work}\n}}' + source[end:]
        found.append(address)
    if found:
        source = '''extern uint64_t private_carbon_audio_enter(uint32_t);
extern void private_carbon_audio_leave(uint64_t);
extern void private_carbon_audio_before(uint32_t, uint32_t, uint32_t);
''' + source
    return source, found
