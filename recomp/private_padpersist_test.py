"""Carbon controller native save/load with the production layout providers.

Premise: production restores 31/31 (PS configuration 3); all five cases 155/155.
ASan/UBSan: production 0/2988 failures; native control 0/2845, both exit 0.
Broken late recipe: 10/155 lost, 5/3047 failed checks, exit 1.
Broken omitted reader: 27/155 lost, 8/1403 failed checks, exit 1.
No persistence fix or sidecar is needed for this same-controller/layout boundary.
The native control also restores everything: a failing retail persistence baseline
would contradict the no-change premise. No emulator, game, devices or sidecar.
The 31 items are two configuration properties and 29 native controller rows;
the two captured remaps are included in those rows (27 other rows).
Exit 3 without the private image and translated outputs.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
# Individual translated originals, normalized definition name only.
BASELINES = {
    0x004710B0: 'fcfe4e571d9b2240e1103532d3e01c9e03b80176dceb8aa537c3c97c4f1efa93',
    0x004727B0: '8c749791cb03fc0ea3057bf6ab715ad7cbd9837444f230bf895a9e598eeb92bd',
    0x0049DBA0: '67148dd666a4e36cd0bd5798c1fce6d8c9b361d07b3825a1956e425770955d2f',
    0x0049DBF0: 'bfd8469a8a4a5cac3c19f25519ee5b62651e2b792895b767574c1c8c78df3c57',
    0x0049DCC0: '2b640d79ea49edb0b3b840b5ddcb62b8f8c6cd7f6f7d0539a2cb2c382bb1b8c6',
    0x0049E400: 'e49a4aeca80d3426c8dfb6ac9fd94d619a59c908294da23747d6f66d281cccc2',
    0x004A0490: 'b62414129afe06aef1c2aaf09b8d5d949a464daf14c3d9a1b6905d428bc4158b',
    0x004A04E0: '72c77d3b70fc7c2be33b7448424ebe51de5ce9a875c399bcfabf0bef62d8f664',
    0x004A4380: '4632e15abf7e63eb19dfd998f13ce8d8a1aa69c1116147b69172690612a6d146',
    0x004A43E0: '1a1eef5c18d4b0becb5228285aea80d15709668284bbdf17e140e6b6e7714ece',
    0x004A4BA0: '2b8e257ce1c736bd0204d6e7f0438d90c149ec2b033d641cdae5d20adad4a91f',
    0x004A4C00: '47d80a232e765fb4cc1286b06822675d0863d123212ffae9a435701854b1ea96',
    0x004A5700: '6005f77c2f2bc7f44dac95ab45178e78ca6c13daa0d90d9cd0396b4a0b0086d5',
    0x004B01F0: '7b1fdd5a8fb8d61cf510043156a4d7e40e4a3b9c3903cfeaa8e3b4f6d21a7043',
    0x004B0270: '4a3b414d128cdddf40e73eb6ec6eee60e6e9e21647487248949500113c07aadf',
    0x0058DB00: 'd334fe4deb0438f7ce15da369a3c107b333a5be380f8e0811a3bb4a7c10f5bd3',
    0x006796D0: '425c89b780caebe4c260899b1461072fbea1bc954d00d844ad3bb9ed9f77d2f1',
    0x00679E70: '78a6c2af9c63f94e74a026cb80efa6ecb8168ef26099682f1ecb6fdc542a455a',
    0x00679EC0: '614d85abfafb793f3878e0ecbcfca7819ad07ff49f61f7e50f343bc916f8b6be',
    0x0067A130: '9577ffec85d199a08de34619034f551492f345b0ced962e70a4d482331f38114',
    0x0067A340: 'bb02451d80340a7a1b619cab3e2ae8d5179e018313ea31fec43517197383a406',
    0x00680510: '777421b270b151662a6f64a00880fced638ca2608afdb00c80c60145daa54586',
    0x00680890: '97316b568c436cba4f96b5535674eda8f72633b1aa46a21de913781604c062c7',
    0x00689550: '924443c8f1adc3817cdb502c46df8c8cb3d014af658acb7e43077dae494a5fb1',
    0x00692240: 'd87850ca629638da2e7510ab75d758172044906987e32458cd8e0902ca7d6630',
    0x006924F0: '66ac453a73d32430ef7361edb4ae047dc1b0cc6134c7323a190bea8967794140',
}


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (args[:3], result.returncode,
                                          result.stdout[-2400:], result.stderr[-3500:])
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / p).is_file() for p in ('image.json','table.c','funcs.h','NFSC.a')):
        print('SKIP: private pad persistence needs Carbon build outputs')
        return 3
    image = json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private pad persistence needs the private image')
        return 3
    sys.path.insert(0,str(HERE))
    import recomp
    import private_hooks
    from private_padbind_test import body, NATIVE
    pe = recomp.PE(image['exe'], expected_sha256=IMAGE_SHA)
    assert image['sha256'] == IMAGE_SHA
    starts = [int(v.strip().removesuffix('u'),16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)',(base/'table.c').read_text())[1].split(',')]
    functions = dict(NATIVE)
    functions.update({a:f'f_{a:08X}' for a in (
        0x49E400,0x4B0270,0x67A130,0x679E70,0x679EC0,0x680510,0x680890,
        0x4B01F0,0x4727B0,0x58DB00)})
    cache, native = {}, []
    for a,name in functions.items():
        chunk = starts.index(a)//800
        if chunk not in cache:
            cache[chunk]=(base/f'NFSC_{chunk:02d}.c').read_text()
        source=cache[chunk]
        original=private_hooks.original_name(a)
        if f'void {original}(' not in source: original=f'f_{a:08X}'
        fragment=body(source,original).replace(original,f'f_{a:08X}',1)
        assert hashlib.sha256(fragment.encode()).hexdigest()==BASELINES[a], hex(a)
        native.append(fragment.replace(f'f_{a:08X}',name,1))
    memory=bytearray(0xC00000)
    for _,_,va,raw_size,raw in pe.sections:
        memory[pe.base+va:pe.base+va+raw_size]=pe.data[raw:raw+raw_size]
    with tempfile.TemporaryDirectory(prefix='private-padpersist-') as directory:
        tmp=Path(directory)
        (tmp/'image.bin').write_bytes(memory)
        (tmp/'native.inc').write_text('\n\n'.join(native)+'\n')
        fixture=(PRIVATE/'carbon_padpersist_fixture.h').read_text()
        (tmp/'fixture.c').write_text(fixture)
        binary=tmp/'fixture'
        run(['clang','-std=c11','-O0','-g','-fsanitize=address,undefined',
             '-fno-sanitize-recover=all','-I',tmp,'-I',PRIVATE,'-I',ROOT/'runtime',
             '-I',HERE,'-I',base,tmp/'fixture.c','-o',binary])
        for label,retail,broken,expected in (
                ('production',0,0,0),('native-control',1,0,0),
                ('recipe-after-load',0,1,1),('missing-native-reader',0,2,1)):
            result=run([binary,tmp/'image.bin',retail,broken],expected)
            summary=re.search(r'private_padpersist checks=(\d+) failures=(\d+) lost=(\d+)/155',result.stdout)
            assert summary, result.stdout
            assert (int(summary[2])>0)==bool(expected), result.stdout
            if not expected:
                assert summary[3]=='0',result.stdout
            else:
                assert int(summary[3])>0,result.stdout
            print(f'{label}: exit={expected}')
            print(result.stdout,end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
