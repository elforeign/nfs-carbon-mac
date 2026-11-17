"""Wrap the private mode reader; retain retail register/stack/default behavior.

Only the pinned Carbon archive receives these wrappers. Startup 0073099A and
00731216 call 00712AC0; 00710100 stores its dimensions in D3DPRESENT_PARAMETERS
00AB06FC/00AB0700 and window globals 00AB0AC8/00AB0ACC. Retail view/viewport
code consumes those globals. No projection, FE transform or HUD layout changes.
"""
import re
from private_render import function_span

CARBON_SHA256 = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
HOOKS = {0x00712AC0: 0, 0x005983F0: 1, 0x005EA6A0: 2, 0x004A0490: 3}


def instrument(source, sha256):
    if sha256 != CARBON_SHA256:
        return source, []
    found = []
    for address, kind in HOOKS.items():
        symbol = f'f_{address:08X}'
        if not re.search(r'void ' + symbol + r'\(', source):
            continue
        begin, end = function_span(source, symbol)
        declaration = source.rfind('void ', 0, begin)
        original = source[declaration:end].replace(symbol + '(', symbol + '_resolution_original(', 1)
        if kind == 0:
            wrapper = f'''\nvoid {symbol}(Cpu *c) {{
    if (!private_carbon_resolution_active()) {{ {symbol}_resolution_original(c); return; }}
    uint8_t *const G = guest_base();
    uint32_t width=M32(c->esp+4), height=M32(c->esp+8);
    {symbol}_resolution_original(c);
    private_carbon_resolution_write(width, height);
}}'''
        else:
            key = 'M32(c->esp+8)' if kind == 3 else 'M32(c->esp+4)'
            test = 'diag_on && M32(c->esp+4)==0x13BEu' if kind == 3 else 'diag_on'
            wrapper = f'''\nvoid {symbol}(Cpu *c) {{
    uint8_t *const G = guest_base();
    if (!({test})) {{ {symbol}_resolution_original(c); return; }}
    uint32_t key={key}, caller=M32(c->esp);
    {symbol}_resolution_original(c);
    private_carbon_resolution_evidence({kind}, key, c->eax, caller);
}}'''
        source = source[:declaration] + original + wrapper + source[end:]
        found.append(address)
    if found:
        source = '''extern int diag_on;
extern int private_carbon_resolution_active(void);
extern void private_carbon_resolution_write(uint32_t, uint32_t);
extern void private_carbon_resolution_evidence(unsigned, uint32_t, uint32_t, uint32_t);
''' + source
    return source, found
