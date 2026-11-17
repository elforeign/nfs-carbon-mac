"""Private-image pointer superset; no prologue, alignment or predecessor rules.

Candidates are data DWORD windows (including unaligned ones) and every text
immediate/displacement. Raw text DWORDs also cover operand fields hidden by
inline data or overlapping linear decodes. Baseline bodies mean reachable instruction bytes, not
the interval up to the next manifest entry. Candidates are accepted in batches
against that frozen body map, so discovery order cannot suppress a sibling.
"""
import collections
import re
import time
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import recomp

HEX = re.compile(r'(?<![\w])(-\s*)?0x([0-9a-f]+)')
DIRECT = re.compile(r'0x([0-9a-f]+)')


def expand(pe, functions):
    begin = time.perf_counter()
    _, size, va, raw_size, _ = next(s for s in pe.sections if s[0].rstrip(b'\0') == b'.text')
    lo, hi = pe.base+va, pe.base+va+min(size, raw_size)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    known = {a for a, _, _ in functions}
    witnesses = collections.defaultdict(list)
    witness_counts = collections.Counter()
    decoded = {}

    def reference(value, kind, site):
        value &= 0xffffffff
        if lo <= value < hi:
            witness_counts[value] += 1
            if len(witnesses[value]) < 8:
                witnesses[value].append({'kind': kind, 'site': site})

    def operands(at, ops):
        for match in HEX.finditer(ops):
            value = int(match[2], 16) * (-1 if match[1] else 1)
            reference(value, 'text_operand', at)

    def decode(pc):
        if pc not in decoded:
            raw = pe.read(pc, min(15, hi-pc)) if lo <= pc < hi else None
            item = next(md.disasm_lite(raw, pc), None) if raw else None
            decoded[pc] = item
        return decoded[pc]

    # Scan every byte window rather than assuming data pointers are aligned.
    data_windows = 0
    for name, virtual_size, data_va, count, raw in pe.sections:
        if name.rstrip(b'\0') not in (b'.rdata', b'.data'):
            continue
        blob = pe.data[raw:raw+count] + b'\0'*max(0, virtual_size-count)
        for off in range(max(0, len(blob)-3)):
            reference(int.from_bytes(blob[off:off+4], 'little'), 'data_dword', pe.base+data_va+off)
            data_windows += 1
    blob = pe.read(lo, hi-lo)
    # Every encoded 32-bit absolute operand is one of these windows, even if
    # the linear sweep lost its instruction boundary. Extra numeric values are
    # intentional over-translation and still face the same body/decode tests.
    for offset in range(max(0, len(blob)-3)):
        reference(int.from_bytes(blob[offset:offset+4], 'little'), 'text_dword', lo+offset)
    off = 0; linear_instructions = 0
    while off < len(blob):
        for at, count, _, ops in md.disasm_lite(blob[off:], lo+off):
            off = at+count-lo; linear_instructions += 1
            operands(at, ops)
        if off < len(blob):
            off += 1

    # Recursive body coverage excludes padding and inline switch words. Follow
    # branch targets, but calls belong to their separate entries. Known entries
    # are independent roots; shared tails still count as occupied instruction bytes.
    occupied = bytearray(hi-lo)
    visited = bytearray(hi-lo)
    body_invalid = []
    baseline_decoder = recomp.Recompiler(pe=pe, functions={a: hi for a in known},
                                         mw_patches=False, import_thunks=True)
    baseline_decoder.calls = True
    for entry in sorted(known):
        # Use precisely the translator's recursive body, including computed
        # switch cases and shared tails. A next-entry numeric interval would
        # incorrectly occupy padding, tables and missed functions.
        baseline_decoder.tables = {}; baseline_decoder.ft_exits = {}
        baseline_decoder.int3_stops = set()
        try:
            instructions = baseline_decoder.discover(entry, hi)
        except recomp.Unsupported:
            instructions = None
        if instructions is not None:
            for instruction in instructions:
                at, count = instruction.address, instruction.size
                mnemonic, ops = instruction.mnemonic, instruction.op_str
                decoded[at] = (at, count, mnemonic, ops)
                operands(at, ops)
                if mnemonic != 'int3' and lo <= at < at+count <= hi:
                    occupied[at-lo:at+count-lo] = b'\1'*count
            continue
        # Retain partial coverage for existing undecodable functions too.
        pending = [entry]
        while pending:
            pc = pending.pop()
            while lo <= pc < hi and not visited[pc-lo]:
                if pc != entry and pc in known:
                    break
                visited[pc-lo] = 1
                item = decode(pc)
                if item is None:
                    body_invalid.append(pc); break
                at, count, mnemonic, ops = item
                operands(at, ops)
                if mnemonic == 'int3':
                    break
                occupied[at-lo:at+count-lo] = b'\1'*count
                target = DIRECT.fullmatch(ops)
                if mnemonic.startswith('j') or mnemonic.startswith('loop'):
                    if target:
                        pending.append(int(target[1], 16))
                    if mnemonic in ('jmp', 'ljmp'):
                        break
                if mnemonic.startswith('ret') or mnemonic in ('hlt', 'ud2'):
                    break
                pc += count

    def clean(entry):
        # This is deliberately a superset predicate, not a proof of every CFG
        # path: decode a contiguous stream through ret/jmp without an invalid
        # opcode. Branch destinations become candidates of their own below.
        seen = {}; pc = entry
        while lo <= pc < hi:
            item = decode(pc)
            if item is None:
                return None, {'reason': 'invalid_opcode', 'site': pc}
            at, count, mnemonic, ops = item
            seen[pc] = item
            if mnemonic.startswith('ret') or mnemonic in ('jmp', 'ljmp'):
                return seen, None
            pc += count
        return None, {'reason': 'leaves_text_without_ret_or_jmp', 'site': pc}

    accepted = {}; rejected = {}; processed = set(); new_instructions = {}
    passes = 0
    while True:
        batch = sorted(set(witnesses)-processed-known)
        if not batch:
            break
        passes += 1
        for entry in batch:
            processed.add(entry)
            if occupied[entry-lo]:
                rejected[entry] = {'reason': 'inside_baseline_body'}
                continue
            instructions, error = clean(entry)
            if error:
                rejected[entry] = error
                continue
            accepted[entry] = len(instructions)
            new_instructions.update(instructions)
            for at, _, _, ops in instructions.values():
                operands(at, ops)
    ordered = sorted(known | set(accepted))
    names = {a: name for a, _, name in functions}
    expanded = [(a, ordered[k+1] if k+1 < len(ordered) else hi,
                 names.get(a, f'superset_{a:08X}')) for k, a in enumerate(ordered)]
    audit = {
        'baseline_functions': len(known), 'functions': len(ordered), 'added': len(accepted),
        'data_windows': data_windows, 'linear_instructions': linear_instructions,
        'candidate_values': len(witnesses), 'known_entry_values': len(set(witnesses) & known),
        'baseline_body_bytes': sum(occupied), 'baseline_invalid_sites': sorted(set(body_invalid)),
        'passes': passes, 'seconds': time.perf_counter()-begin,
        'entries': [{'address': a, 'instructions': n, 'witness_count': witness_counts[a],
                     'witnesses': witnesses[a]} for a, n in sorted(accepted.items())],
        'rejected': [{'address': a, **why, 'witnesses': witnesses[a]} for a, why in sorted(rejected.items())],
        'rejected_by_reason': dict(collections.Counter(v['reason'] for v in rejected.values())),
        'scope': 'all data/text byte-window DWORDs plus decoded text operands; frozen reachable baseline instruction bodies; contiguous clean decode through ret/jmp; branch operands are candidates too',
    }
    return expanded, audit, new_instructions
