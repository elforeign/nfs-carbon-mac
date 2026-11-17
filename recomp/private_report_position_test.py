"""Production readers -> report line: both games, menus, missing car, invalid data.

Broken control replaces the reader with a no-result reader: 1 required line / 0.
Normal reader: 1 required line / 1 for each game. No game assets needed.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = (ROOT / 'runtime/report.m').read_text()
    assert 'report_position(f, flow);' in report.split('static ReportSnapshot *report_capture(', 1)[1]
    diag = (ROOT / 'runtime/diag.c').read_text()
    mw = diag[diag.index('float diag_car_speed(void) {'):diag.index('static void stats_second(', diag.index('float diag_car_speed(void) {'))]
    carbon = (ROOT / 'recomp/private_runtime/carbon_skipfe.h').read_text()
    carbon = carbon[carbon.index('int private_carbon_player_pose('):carbon.index('static void private_carbon_skipfe_setup(')]
    flow = (ROOT / 'recomp/private_runtime/carbon_report_flow.c').read_text().replace('#include "host.h"', '')
    prelude = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
static uint8_t memory[0x1000000], *G = memory;
#define M32(a) (*(uint32_t *)(G + (uint32_t)(a)))
#define MF32(a) (*(float *)(G + (uint32_t)(a)))
#define PRIVATE_CARBON_SKIPFE 1
#define NFS_GAME_MW 1
'''
    fixture = r'''
int main(void) {
#if NFS_GAME == NFS_GAME_MW
    M32(0x008EF998) = 1; M32(0x009142D0) = 0x1000; M32(0x1034) = 0x2000;
    MF32(0x2040) = 12.5; MF32(0x2044) = -34.25; MF32(0x2048) = 56;
    MF32(0x2010) = 1; MF32(0x2038) = 1;
    M32(0x009A3A20) = 0x3000; strcpy((char *)G + 0x3040, "native-track");
#else
    M32(0x00A9FF64) = 1; M32(0x00A9FF5C) = 0x1000; M32(0x1000) = 0x2008;
    M32(0x2008) = 0x3000; M32(0x3004) = 0x0076E810; M32(0x2000) = 0x4000;
    M32(0x4000) = 0x5000; M32(0x5060) = 0x006D7EA0;
    M32(0x404c) = 0x6000; M32(0x6000) = 0x7000; M32(0x7020) = 0x006C6FF0;
    M32(0x6030) = 0x8000; M32(0x8000) = 0x9000;
    MF32(0x9010) = 34.25; MF32(0x9014) = 56; MF32(0x9018) = 12.5;
    MF32(0x9098) = 1;
    M32(0x00A97DE0) = 0xa000; strcpy((char *)G + 0xa040, "native-track");
#endif
    report_position(stdout, 6);
    report_position(stdout, 3);
    report_position(stdout, 4);
#if NFS_GAME == NFS_GAME_MW
    MF32(0x2040) = NAN;
#else
    MF32(0x9010) = NAN;
#endif
    report_position(stdout, 6);
    return 0;
}
'''
    expected = 'position:   x=12.500000 y=-34.250000 z=56.000000; heading (forward)=1.000000,0.000000,0.000000; track=native-track'
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for game, reader in [(1, mw), (2, carbon + flow)]:
            for broken in (False, True):
                body = prelude + reader
                if broken:
                    body += '\n#define report_player_position(pos, forward, track) 0\n' if game == 1 else '\n#define private_report_position(pos, forward, track) 0\n'
                header = (ROOT / 'runtime/report_position.h').read_text()
                if broken:
                    # Keep the production formatter; remove only its reader implementation/declaration.
                    header = header[header.index('static void report_position('):]
                    if game == 2:
                        body += '\n#define report_player_position private_report_position\n'
                body += '\n' + header + fixture
                src, exe = work / 'check.c', work / 'check'
                src.write_text(body)
                subprocess.run(['clang', '-std=c11', '-DNFS_GAME=' + str(game), str(src), '-lm', '-o', str(exe)], check=True, capture_output=True)
                result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
                lines = result.stdout.splitlines()
                want = expected if game == 1 else expected.replace('1.000000,0.000000', '1.000000,-0.000000')
                assert (lines[0] == want) != broken, result.stdout
                assert lines[1:3] == ['position:   not in a race or free roam'] * 2
                assert lines[3] == 'position:   unavailable'
                print(f'game {game}: required position lines={int(lines[0] == want)}; reader empty={int(broken)}')


if __name__ == '__main__':
    main()
