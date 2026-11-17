"""Prove inline switch-data extents from an unsigned bounded indexed dispatch.

The linear sweep can decode table words as instructions across the next method.
Only cmp index, bound / ja default / unmodified index / jmp [index*4+base]
proves this boundary. This does not turn internal case labels into functions.
"""
import re
from capstone import Cs, CS_ARCH_X86, CS_MODE_32, CS_OP_IMM, CS_OP_REG


def boundaries(pe,instructions,lo,hi):
    md=Cs(CS_ARCH_X86,CS_MODE_32);md.detail=True
    result=[]
    for at,(size,mn,ops) in sorted(instructions.items()):
        if mn!='jmp':continue
        match=re.fullmatch(r'dword ptr \[(e[a-z]{2})\*4 \+ 0x([0-9a-f]+)\]',ops)
        if not match:continue
        reg,base=match[1],int(match[2],16)
        if not at+size<=base<hi:continue
        jump=next(md.disasm(pe.read(at,size),at),None)
        if jump is None:continue
        index=jump.operands[0].mem.index
        previous=[]
        for pc in range(max(lo,at-64),at):
            row=instructions.get(pc)
            if row:
                item=next(md.disasm(pe.read(pc,row[0]),pc),None)
                if item:previous.append(item)
        for k,cmp in enumerate(previous):
            if cmp.mnemonic!='cmp' or len(cmp.operands)!=2:continue
            a,b=cmp.operands
            if a.type!=CS_OP_REG or a.reg!=index or b.type!=CS_OP_IMM or not 0<=b.imm<1024:continue
            tail=previous[k+1:]
            if not tail or tail[0].mnemonic!='ja' or tail[0].address!=cmp.address+cmp.size:continue
            pc=tail[0].address+tail[0].size;valid=True
            for item in tail[1:]:
                _,writes=item.regs_access()
                if item.address!=pc or index in writes or item.mnemonic.startswith(('j','call','ret','loop')):valid=False;break
                pc+=item.size
            count=b.imm+1;end=base+4*count
            if not valid or pc!=at or end>hi:continue
            raw=pe.read(base,4*count)
            if raw is None or len(raw)!=4*count:continue
            values=[int.from_bytes(raw[p:p+4],'little') for p in range(0,len(raw),4)]
            if not all(lo<=v<base for v in values):continue
            result.append({'site':at,'begin':base,'end':end,'entries':count,'case_targets':values})
            break
    return result
