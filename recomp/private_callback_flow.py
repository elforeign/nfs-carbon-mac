"""Bounded interprocedural constant/argument flow for x86 callback operands.

This is static analysis, not x86 execution. Unknown register/object values remain
unknown. Import callback signatures are ABI contracts, not game-specific sites.
"""
import bisect
import collections
import re

CALLBACKS={'_onexit':(0,), 'atexit':(0,), '__dllonexit':(0,), 'qsort':(3,),
           'bsearch':(4,), '_beginthreadex':(2,), 'CreateThread':(2,),
           'SetUnhandledExceptionFilter':(0,), 'SetTimer':(3,), 'EnumWindows':(0,)}
REGS=set('eax ebx ecx edx esi edi ebp esp'.split())


def targets(pe,instructions,functions,lo,hi):
    ordered=sorted(functions);groups=collections.defaultdict(list)
    for address,(size,mn,ops) in sorted(instructions.items()):
        k=bisect.bisect_right(ordered,address)-1
        if k>=0:groups[ordered[k]].append((address,size,mn,ops))
    pops={a:max([int(ops,0) if ops else 0 for _,_,mn,ops in rows if mn=='ret'] or [0]) for a,rows in groups.items()}
    summaries={};found=collections.defaultdict(set);rejected=set()
    def union(*args):return frozenset().union(*args)
    def imported(target,operand):
        if target:
            raw=pe.read(target,6)
            slot=int.from_bytes(raw[2:],'little') if raw and len(raw)==6 and raw[:2]==b'\xff\x25' else 0
        else:
            m=re.fullmatch(r'dword ptr \[0x([0-9a-f]+)\]',operand);slot=int(m[1],16) if m else 0
        return pe.imports.get(slot,'').split('!')[-1]
    for fn,rows in groups.items():
        sp=0;bp=-4;regs={};memory={};callbacks=set();calls=[]
        def slot(offset):
            return memory.get(offset,frozenset({('arg',(offset-4)//4)}) if 4<=offset<260 and offset%4==0 else frozenset())
        def location(op):
            m=re.fullmatch(r'(?:dword ptr )?\[(esp|ebp)(?: ([+-]) (0x[0-9a-f]+|\d+))?\]',op)
            if not m:return None
            delta=(int(m[3],0)*(-1 if m[2]=='-' else 1)) if m[3] else 0
            return (sp if m[1]=='esp' else bp)+delta
        def value(op):
            if op in REGS:return regs.get(op,frozenset())
            try:return frozenset({int(op,0)&0xffffffff})
            except ValueError:pass
            at=location(op)
            if at is not None:return slot(at)
            m=re.fullmatch(r'dword ptr \[0x([0-9a-f]+)\]',op)
            if m:
                address=int(m[1],16)
                # The loader replaces IAT contents with host import thunks.
                # Its on-disk name/ordinal RVA is never a guest code pointer.
                if address in pe.imports:return frozenset()
                raw=pe.read(address,4)
                if raw and len(raw)==4:return frozenset({int.from_bytes(raw,'little')})
            return frozenset()
        def callback(values):
            for v in values:
                if isinstance(v,int) and lo<=v<hi:
                    if v in instructions:found[v].add('resolved_callback_operand')
                    else:rejected.add(v)
                elif isinstance(v,tuple) and v[0]=='arg':callbacks.add(v[1])
        for at,size,mn,ops in rows:
            args=ops.split(', ',1)
            if mn=='push':
                pushed=value(ops);sp-=4;memory[sp]=pushed
            elif mn=='pop':
                if ops in REGS:regs[ops]=slot(sp)
                sp+=4
            elif mn=='mov' and len(args)==2:
                dst,src=args
                if dst=='ebp' and src=='esp':bp=sp
                elif dst=='esp' and src=='ebp':sp=bp
                elif dst in REGS:regs[dst]=value(src)
                else:
                    pos=location(dst)
                    if pos is not None:memory[pos]=value(src)
            elif mn in ('add','sub') and args[0]=='esp':
                try:sp+=int(args[1],0)*(1 if mn=='add' else -1)
                except ValueError:pass
            elif mn=='xor' and len(args)==2 and args[0]==args[1]:regs[args[0]]=frozenset({0})
            elif mn=='lea' and len(args)==2 and args[0] in REGS and re.fullmatch(
                    r'\['+args[0]+r'(?: \+ (?:0x0|0))?\]',args[1]):
                # MSVC alignment NOP, including disp32=0 encodings. The register
                # still holds the callback/forwarded parameter it held before.
                pass
            elif mn in ('call','jmp'):
                values=value(ops);direct=int(ops,16) if re.fullmatch(r'0x[0-9a-f]+',ops) else None
                callee=direct if direct is not None else next((v for v in values if isinstance(v,int) and v in functions),None)
                if direct is None and not imported(None,ops):callback(values)
                imp=imported(callee,ops)
                snapshot={i:slot(sp+4*i+(4 if mn=='jmp' else 0)) for i in range(64)}
                for arg in CALLBACKS.get(imp,()):callback(snapshot[arg])
                if callee in functions:calls.append((callee,snapshot))
                if mn=='call':sp+=pops.get(callee,0)
                for reg in ('eax','ecx','edx'):regs[reg]=frozenset()
            elif args[0] in REGS and mn not in ('cmp','test','nop'):
                regs[args[0]]=frozenset()
        summaries[fn]=(callbacks,calls)
    # Forwarded callback arguments converge monotonically across callers.
    changed=True
    while changed:
        changed=False
        for fn,(args,calls) in summaries.items():
            for callee,actual in calls:
                for index in list(summaries.get(callee,(set(),[]))[0]):
                    for value in actual.get(index,()):
                        if isinstance(value,int) and lo<=value<hi:
                            if value in instructions:found[value].add('forwarded_callback_argument')
                            else:rejected.add(value)
                        elif isinstance(value,tuple) and value[0]=='arg' and value[1] not in args:
                            args.add(value[1]);changed=True
    return found,{'functions_with_callback_parameters':sum(bool(args) for args,_ in summaries.values()),
                  'resolved_callback_targets':len(found),'rejected_noninstruction_values':sorted(rejected),'argument_limit':64,
                  'scope':'constant operands and forwarded stack parameters; unknown computed values are not invented'}
