"""Static callback closure for a private PE; no game addresses or bytes here.

Use instruction boundaries and terminating predecessors to distinguish callable
entries from numeric values. Include direct callees, CRT arrays and witnessed
pointer tables. Audit the whole-image superset as well as the CRT-root graph.
"""
import bisect
import collections
import re
import struct
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import build_all
import listing
import recomp


def complete(pe, funcs, *, superset=False):
    _, size, va, _, _ = next(s for s in pe.sections if s[0].rstrip(b'\0')==b'.text')
    lo,hi=pe.base+va,pe.base+va+size
    md=Cs(CS_ARCH_X86,CS_MODE_32)
    starts,ends=set(),{}
    refs=[]; init_arrays=[]; init_targets=set(); instructions={}
    initial={a for a,_,_ in funcs}; names={a:n for a,_,n in funcs}
    accepted=collections.defaultdict(set)
    for a in initial:accepted[a].add('manifest_or_data')
    data_sections=[s for s in pe.sections if s[0].rstrip(b'\0') in (b'.rdata',b'.data')]
    def data_address(a):return any(pe.base+s[2]<=a<pe.base+s[2]+s[3] for s in data_sections)
    def word(a):
        raw=pe.read(a,4);return int.from_bytes(raw,'little') if raw and len(raw)==4 else 0
    def import_name(mn,ops):
        if mn!='call':return None
        direct=re.fullmatch(r'0x([0-9a-f]+)',ops)
        if direct:
            raw=pe.read(int(direct[1],16),6)
            slot=int.from_bytes(raw[2:],'little') if raw and len(raw)==6 and raw[:2]==b'\xff\x25' else 0
        else:
            m=re.fullmatch(r'dword ptr \[0x([0-9a-f]+)\]',ops);slot=int(m[1],16) if m else 0
        return pe.imports.get(slot)
    def record(a,n,mn,ops,previous=()):
        instructions[a]=(n,mn,ops)
        final=ops.rsplit(', ',1)[-1]
        m=re.fullmatch(r'0x([0-9a-f]+)',final) if mn in ('mov','push','call') else re.fullmatch(r'\[0x([0-9a-f]+)\]',final) if mn=='lea' else None
        if m:
            target=int(m[1],16)
            if lo<=target<hi:refs.append((a,'direct' if mn=='call' else 'code',target,ops))
            elif data_address(target) and mn!='call':refs.append((a,'data',target,ops))
        if mn in ('call','jmp') and not re.fullmatch(r'0x[0-9a-f]+',ops):
            if not import_name('call',ops):refs.append((a,'indirect',None,ops))
        imp=import_name(mn,ops)
        if imp and imp.split('!',1)[-1] in ('_initterm','_initterm_e') and len(previous)>=2:
            p,q=previous[-2:];end=re.fullmatch(r'0x([0-9a-f]+)',p[1]);begin=re.fullmatch(r'0x([0-9a-f]+)',q[1])
            if p[0]==q[0]=='push' and begin and end:
                begin,end=int(begin[1],16),int(end[1],16)
                if data_address(begin) and data_address(end-1) and 0<=end-begin<=1<<20 and (end-begin)%4==0:
                    roots=[word(at) for at in range(begin,end,4) if lo<=word(at)<hi]
                    init_arrays.append({'site':a,'begin':begin,'end':end,'targets':roots});init_targets.update(roots)
    blob=pe.read(lo,hi-lo);off=0;previous=[]
    while off<len(blob):
        for a,n,mn,ops in md.disasm_lite(blob[off:],lo+off):
            off=a+n-lo;starts.add(a);ends[a+n]=(a,listing.kind(mn,ops));record(a,n,mn,ops,previous)
            previous=(previous+[(mn,ops)])[-2:]
        if off<len(blob):off+=1;previous=[]
    def valid(a):
        return lo<=a<hi and (build_all.plausible_start(a,starts,ends) or pe.read(a,3)==b'\x55\x8b\xec')
    for site,kind,target,ops in refs:
        if kind=='direct' or (kind=='code' and valid(target)):accepted[target].add(kind)
    for a in init_targets:accepted[a].add('crt_initializer')
    data_targets=collections.defaultdict(list)
    for name,vs,va,rs,raw in data_sections:
        for k in range(0,rs-3,4):
            a=int.from_bytes(pe.data[raw+k:raw+k+4],'little')
            if lo<=a<hi:
                data_targets[a].append(pe.base+va+k)
                if valid(a):accepted[a].add('data_pointer')
    # Bounded inline switch data can make a linear sweep consume the first
    # bytes of a following method. An independently referenced entry at the
    # proven end of that table is an instruction boundary, even without a frame
    # prologue or padding byte. Internal switch labels stay inside their owner.
    from private_inline_tables import boundaries
    inline_tables=boundaries(pe,instructions,lo,hi)
    witnessed=set(data_targets)|{t for _,kind,t,_ in refs if kind in ('code','direct')}
    inline_entries=[]
    for table in inline_tables:
        target=table['end']
        if target not in witnessed:continue
        if not next(md.disasm_lite(pe.read(target,16) or b'',target),None):continue
        starts.add(target);ends.pop(target,None)
        if target not in accepted:inline_entries.append(target)
        accepted[target].add('after_bounded_inline_table')
    # A referenced table with a recognized first entry witnesses its remaining
    # entries even if those methods have no padding/canonical frame prologue.
    tables={}
    def expand_tables():
        for site,kind,base,ops in refs:
            if kind!='data' or base in tables:continue
            first=word(base)
            if first not in accepted and not valid(first):continue
            entries=[];at=base
            while data_address(at):
                target=word(at)
                if not lo<=target<hi:break
                # Text strings can look like an array of in-range addresses.
                # A new table entry must start an instruction; decoding bytes
                # from the middle of an immediate is not evidence of a method.
                if target not in starts and target not in accepted:break
                if not next(md.disasm_lite(pe.read(target,16) or b'',target),None):break
                entries.append(target);accepted[target].add('referenced_pointer_table');at+=4
            if entries:tables[base]=entries
    expand_tables()
    # Re-decode every new entry: a linear sweep may have missed a direct callee
    # hidden behind inline data. This reaches a fixed point without emulation.
    seen=set()
    def walk(pending):
        while pending:
            pc=pending.pop()
            while lo<=pc<hi and pc not in seen:
                seen.add(pc);item=next(md.disasm_lite(pe.read(pc,16) or b'',pc),None)
                if item is None:break
                a,n,mn,ops=item;before=len(refs);record(a,n,mn,ops)
                for site,kind,target,arg in refs[before:]:
                    if kind=='direct' or (kind=='code' and valid(target)):
                        if target not in accepted:pending.append(target)
                        accepted[target].add(kind)
                if mn.startswith('j') or mn.startswith('loop'):
                    m=re.fullmatch(r'0x([0-9a-f]+)',ops)
                    if m:pending.append(int(m[1],16))
                if mn.startswith('ret') or mn in ('jmp','hlt','ud2','int3'):break
                pc+=n
    walk(list(accepted))
    from private_callback_flow import targets as callback_targets
    for passes in range(8):
        before=set(accepted)
        expand_tables();walk(list(set(accepted)-before))
        resolved,flow=callback_targets(pe,instructions,set(accepted),lo,hi)
        for target,reasons in resolved.items():accepted[target].update(reasons)
        alternate=[];invalid=[]
        limits={a:hi for a in accepted}
        for target in flow['rejected_noninstruction_values']:
            decoder=recomp.Recompiler(pe=pe,functions=limits,mw_patches=False,import_thunks=True);decoder.calls=True
            try:decoder.discover(target,hi)
            except recomp.Unsupported as error:invalid.append({'value':target,'reason':str(error)})
            else:accepted[target].add('decoded_alternate_callback');alternate.append(target)
        flow['validated_alternate_entries']=alternate;flow['invalid_noninstruction_values']=invalid
        walk(list(set(accepted)-before))
        if set(accepted)==before:break
    else:raise RuntimeError('callback discovery did not converge in 8 passes')
    flow['fixed_point_passes']=passes+1
    superset_audit=None
    if superset:
        from private_superset import expand
        seeds=[(a,hi,names.get(a,f'static_ref_{a:08X}')) for a in sorted(accepted)]
        expanded,superset_audit,new_instructions=expand(pe,seeds)
        for a,_,name in expanded:
            if a not in accepted:
                accepted[a].add('private_superset');names[a]=name
        for a,n,mn,ops in new_instructions.values():record(a,n,mn,ops)
    ordered=sorted(accepted);known=set(ordered)
    entry=getattr(pe,'entry',None)
    if entry is None:
        nt=struct.unpack_from('<I',pe.data,60)[0];entry=pe.base+struct.unpack_from('<I',pe.data,nt+24+16)[0]
    edges=collections.defaultdict(set); indirect={}
    for site,kind,target,ops in refs:
        index=bisect.bisect_right(ordered,site)-1
        if index<0:continue
        owner=ordered[index]
        if kind in ('code','direct') and target in known:edges[owner].add(target)
        elif kind=='data':
            edges[owner].update(tables.get(target,[]))
            value=word(target)
            if value in known:edges[owner].add(value)
        elif kind=='indirect':indirect[site]={'site':site,'owner':owner,'operand':ops}
    roots={entry}|init_targets;reachable=set();todo=list(roots)
    while todo:
        a=todo.pop()
        if a in reachable:continue
        reachable.add(a);todo.extend(edges[a]-reachable)
    rejected=[{'site':site,'target':target,'operand':ops} for site,kind,target,ops in refs if kind=='code' and target not in known]
    audit={'callback_argument_flow':flow,'initial_functions':len(initial),'functions':len(known),'added':len(known-initial),
           'bounded_inline_tables':inline_tables,'inline_table_recovered_entries':sorted(set(inline_entries)),
           'crt_initializer_arrays':init_arrays,'crt_initializer_targets':len(init_targets),
           'static_targets_by_reason':dict(collections.Counter(reason for reasons in accepted.values() for reason in reasons)),
           'uncovered_enumerated_targets':sorted(set(t for a in init_arrays for t in a['targets'])-known),
           'crt_graph_reachable_functions':len(reachable),'crt_graph_reachable_starts':sorted(reachable),'crt_graph_indirect_sites':[r for r in indirect.values() if r['owner'] in reachable],
           'unclassified_code_values':list({(r['site'],r['target']):r for r in rejected}.values()),
           'starts':[{'address':a,'reasons':sorted(accepted[a])} for a in ordered],
           'tables':[{'address':a,'targets':targets} for a,targets in sorted(tables.items())],
           'scope':'whole-image static reference superset; runtime-computed indirect values remain opaque'}
    if superset_audit is not None:audit['superset']=superset_audit
    return [(a,ordered[k+1] if k+1<len(ordered) else hi,names.get(a,f'static_ref_{a:08X}')) for k,a in enumerate(ordered)],audit
