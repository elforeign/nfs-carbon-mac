"""Named Winsock dispatch, guest ABI and honest implementation coverage.

Red: original dispatch 6 checks / 4 failures; coverage rejected 0/1 missing APIs.
Green: expanded dispatch 64 checks / 0 failures; coverage rejects 1/1 missing APIs.
Persistent original-routing control: 64 checks / 8 failures; missing-target controls: 7/7. Host transport is faked by ws2_policy_test.c;
no packets, resolver queries, game image, GPU or emulation are needed.
"""
from pathlib import Path
import json
import re
import subprocess
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]

# Independent Win32 API arities, covering the image's 38 distinct Winsock imports.
ARITIES = {
    0: 'WSACleanup WSACreateEvent WSAGetLastError',
    1: 'WSACloseEvent WSAResetEvent WSASetEvent closesocket htonl htons inet_addr inet_ntoa ntohl ntohs gethostbyname',
    2: 'WSAStartup gethostname getservbyname getservbyport listen shutdown',
    3: 'accept bind connect gethostbyaddr getpeername getsockname ioctlsocket socket',
    4: 'recv send',
    5: 'WSAGetOverlappedResult WSAWaitForMultipleEvents getsockopt select setsockopt',
    6: 'recvfrom sendto', 7: 'WSARecv', 9: 'WSAIoctl WSARecvFrom',
}
# ntohl/ntohs are useful extra ABI checks; the image uses the same byte swaps via hton*.
IMPORTS = {name for names in ARITIES.values() for name in names.split()} - {'ntohl', 'ntohs'}

HARNESS = r'''
#include <netdb.h>
#include <string.h>
static char *service_aliases[] = {"www", NULL};
static struct servent service = {"http", service_aliases, 0, "tcp"};
static struct servent *test_service_name(const char *name, const char *proto) {
    return !strcmp(name,"http") && (!proto || !strcmp(proto,"tcp")) ? &service : NULL;
}
static struct servent *test_service_port(int port, const char *proto) {
    return port == service.s_port && (!proto || !strcmp(proto,"tcp")) ? &service : NULL;
}
#define getservbyname test_service_name
#define getservbyport test_service_port
#define main policy_main
#include "ws2_policy_test.c"
#undef main
#include "game_ws2.h"
static uint32_t named(const char *fn, unsigned n, ...) {
    Cpu c = {0}; c.esp = 0x1000;
    va_list ap; va_start(ap, n);
    for (unsigned i=0; i<n; ++i) M32(c.esp+4+4*i)=va_arg(ap,uint32_t);
    va_end(ap);
    int handled=private_ws2(&c,fn);
    check(handled==1 && c.esp==0x1004+4*n,"named dispatch and stdcall cleanup");
    return c.eax;
}
int main(void) {
    G=calloc(1, 16*1024*1024);
    socks[0].fd=101; socks[0].type=2;
    M32(0x2000)=1;
    check(named("ioctlsocket",3,SOCK_BASE,0x8004667Eu,0x2000u)==0 && socks[0].guest_nonblock,
          "named FIONBIO changes guest blocking mode");
    M32(0x2000)=0;
    check(invoke("#10",3,SOCK_BASE,0x8004667Eu,0x2000u)==0 && !socks[0].guest_nonblock,
          "legacy MW ordinal 10 remains ioctl");
    strcpy((char *)G+0x2100,"127.0.0.1");
    check(named("inet_addr",1,0x2100u)==htonl(INADDR_LOOPBACK),"inet_addr loopback byte order");
    strcpy((char *)G+0x2100,"255.255.255.255");
    check(named("inet_addr",1,0x2100u)==INADDR_NONE,"inet_addr broadcast");
    strcpy((char *)G+0x2100,"invalid");
    check(named("inet_addr",1,0x2100u)==INADDR_NONE,"inet_addr invalid");
    uint32_t text=named("inet_ntoa",1,htonl(INADDR_LOOPBACK));
    check(text && !strcmp((char *)G+text,"127.0.0.1"),"inet_ntoa guest string");
    M32(0x2100)=htonl(INADDR_LOOPBACK);
    uint32_t he=named("gethostbyaddr",3,0x2100u,4u,2u);
    check(he && !strcmp((char *)G+M32(he),"127.0.0.1") && M32(he+4) &&
          M32(M32(he+4))==0 && M32(he+8)==0x00040002 &&
          M32(M32(he+12)+4)==0 && M32(M32(M32(he+12)))==htonl(INADDR_LOOPBACK),
          "gethostbyaddr marshals 32-bit hostent");
    check(named("gethostbyaddr",3,0x2100u,4u,23u)==0 && wsa_err==10047,"reverse unsupported family");
    check(named("gethostbyaddr",3,0x2100u,3u,2u)==0 && wsa_err==10014,"reverse bad length");
    strcpy((char *)G+0x2100,"http"); strcpy((char *)G+0x2140,"tcp");
    service.s_port=htons(80);
    uint32_t se=named("getservbyname",2,0x2100u,0x2140u);
    check(se && !strcmp((char *)G+M32(se),"http") && M32(se+8)==htons(80) &&
          !strcmp((char *)G+M32(se+12),"tcp") &&
          !strcmp((char *)G+M32(M32(se+4)),"www") && M32(M32(se+4)+4)==0,
          "service guest layout, aliases and network-order port");
    check(named("getservbyport",2,(uint32_t)htons(80),0u)==se,"service lookup by network-order port");
    check(named("getservbyport",2,0u,0u)==0 && wsa_err==11004,"service not found");
    /* ALL_IMPORTS */
    printf("PRIVATE WS2: %u checks, %u failures\n",checks,failures);
    return failures ? 1 : 0;
}
'''


def inventory(directory, ws, adapter, imports):
    """Execute prepare's production coverage block with a minimal staged runtime."""
    dst = directory / 'runtime'
    dst.mkdir(exist_ok=True)
    for name in ('private_crt.c', 'private_win32.c', 'security.h', 'boot.c', 'threads.c',
                 'heap.c', 'd3dx.c', 'd3dx_effect.c', 'user32.m', 'dsound.c', 'dinput.c',
                 'd3d9.m', 'game_d3dx.h'):
        (dst / name).write_text('')
    (dst / 'game_ws2.h').write_text(adapter)
    (dst / 'ws2_32.c').write_text(ws)
    source = (ROOT / 'recomp/build_private_runtime.py').read_text()
    block = source.split('    # Coverage is a reviewable inventory, not a claim of boot reachability.\n', 1)[1].split('    return dst', 1)[0]
    scope = dict(dst=dst, out=directory, image={'imports':dict(enumerate(imports))}, re=re, json=json)
    exec(textwrap.dedent(block), scope)
    return {r['import']:r['status'] for r in scope['coverage']}


def main():
    ws = (ROOT / 'runtime/ws2_32.c').read_text()
    adapter = (ROOT / 'recomp/private_runtime/game_ws2.h').read_text()
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        source = directory / 'test.c'
        calls = '\n'.join('    named(%s,%d,%s);' % (json.dumps(name), n,
                          ','.join('0x2200u' if name == 'select' and i == 4 else '0u' for i in range(n)))
                          if n else '    named(%s,0);' % json.dumps(name)
                          for n, names in ARITIES.items() for name in names.split())
        source.write_text(HARNESS.replace('/* ALL_IMPORTS */', calls))
        (directory / 'game_ws2.h').write_text(adapter)
        binary = directory / 'test'
        subprocess.run(['clang','-O1','-Wno-unused-function','-I'+str(ROOT/'runtime'),
                        '-I'+str(ROOT/'recomp'),'-I'+str(ROOT/'recomp/out'),
                        '-I'+str(ROOT/'recomp/private_runtime'),str(source),'-o',str(binary)],
                       check=True, capture_output=True, text=True)
        result = subprocess.run([str(binary)],capture_output=True,text=True)
        print(result.stdout, end='')
        # Restore both original routing defects while running exactly the same checks.
        broken_ws = directory / 'broken_ws2.c'
        broken_ws.write_text(ws.replace('case 12:', 'case 999:'))
        (directory / 'game_ws2.h').write_text(adapter.replace('int private_ws2(Cpu *c, const char *fn) {',
            'int private_ws2(Cpu *c, const char *fn) {\n    if (!strcmp(fn, "inet_addr")) fn = "#10";'))
        broken_binary = directory / 'broken'
        subprocess.run(['clang','-O1','-Wno-unused-function', '-DWS2_C=' + json.dumps(str(broken_ws)),
                        '-I'+str(ROOT/'runtime'), '-I'+str(ROOT/'recomp'),
                        '-I'+str(ROOT/'recomp/out'),str(source),'-o',str(broken_binary)],
                       check=True, capture_output=True, text=True)
        broken_result = subprocess.run([str(broken_binary)], capture_output=True, text=True)
        print('Original-routing control: ' + broken_result.stdout.splitlines()[-1])
        detects_original = broken_result.returncode == 1 and '0 failures' not in broken_result.stdout
        # A name-to-ordinal mapping alone must not count as an implementation.
        missing = adapter + '\n// fixture\nif (!strcmp(fn, "missing_api")) fn = "#999";\n'
        coverage = inventory(directory, ws, missing, ['ws2_32.dll!missing_api'])
        honest = coverage['ws2_32.dll!missing_api'] == 'stub'
        print('PRIVATE WS2 coverage: %d/1 missing implementations rejected' % honest)
        imports = ['ws2_32.dll!' + name for name in sorted(IMPORTS)]
        mapped = inventory(directory, ws, adapter, imports)
        complete = len(IMPORTS) == 38 and all(status != 'stub' for status in mapped.values())
        print('PRIVATE WS2 import coverage: %d/%d implemented' %
              (sum(status != 'stub' for status in mapped.values()), len(mapped)))
        # Remove each real dispatch target in turn; aliases must become stubs too.
        mutations = [('ioctlsocket', ws.replace('case 12:', 'case 999:')),
                     ('inet_ntoa', ws.replace('case 11:', 'case 999:')),
                     ('gethostbyaddr', ws.replace('case 51:', 'case 999:')),
                     ('getservbyname', ws.replace('case 55:', 'case 999:')),
                     ('getservbyport', ws.replace('case 56:', 'case 999:')),
                     ('inet_addr', ws.replace('!strcmp(fn, "inet_addr")', '!strcmp(fn, "removed")')),
                     ('WSACreateEvent', ws.replace('!strcmp(fn, "WSACreateEvent")', '!strcmp(fn, "removed")'))]
        rejected = 0
        for name, broken in mutations:
            row = inventory(directory, broken, adapter, ['ws2_32.dll!' + name])
            rejected += row['ws2_32.dll!' + name] == 'stub'
        print('PRIVATE WS2 coverage controls: %d/%d rejected' % (rejected, len(mutations)))
        return int(result.returncode != 0 or not detects_original or not honest or not complete or rejected != len(mutations))


if __name__ == '__main__':
    raise SystemExit(main())
