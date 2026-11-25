"""Exact notch native size through Cocoa geometry and both mode selectors.

Proof: good=0 failures; original provider, MW cap and Carbon cap each exit=1.
Off: 3456x2168 provider -> MW 3440x2160 / Carbon 2560x1440, unchanged.
On: 3456x2234 provider -> both 3456x2234, below the 8294400 pixel cap.
No application, real window, GPU or private game assets are needed.
"""
from pathlib import Path
import hashlib
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
RT = ROOT / 'runtime'
PRIVATE = ROOT / 'recomp/private_runtime'


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


# Original failing arithmetic, independently pinned fragments of the functions.
OLD_PROVIDER = '*h = (int)((screen_h - (notch_fill() ? 0 : screen_top_inset)) * screen_scale) & ~7;'
OLD_MW = '''double cap = fmin(1.0, fmin(3840.0 / dw, 2160.0 / dh));            // native, at most 4K
    uint32_t nw = (uint32_t)(dw * cap) & ~7u, nh = (uint32_t)(dh * cap) & ~7u;'''
OLD_CARBON = 'if (w > 3840 || h > 2160 || w > (uint32_t)dw || h > (uint32_t)dh) continue;'
for fragment, digest in (
    (OLD_PROVIDER, '3bbdcb6b32e1e4aa13f52f953a1beef6d6280a375c859ac892b8d19114bb8f6c'),
    (OLD_MW, 'd57e6b03c1b83592b30f6bca0594ac79fbbaec801312dd0650b73cfec5714185'),
    (OLD_CARBON, '7de44c355965a1c50d4d9aec03e207f528024f0ba4eed336c0baa008be2ec745'),
):
    assert hashlib.sha256(fragment.encode()).hexdigest() == digest

HARNESS = r'''
#import <Cocoa/Cocoa.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <string.h>
@interface FixtureScreen : NSObject
@property NSRect frame, visibleFrame;
@property NSEdgeInsets safeAreaInsets;
@property CGFloat backingScaleFactor;
+ (instancetype)mainScreen;
@end
static FixtureScreen *screen;
@implementation FixtureScreen
+ (instancetype)mainScreen { return screen; }
@end
#define NSScreen FixtureScreen
typedef struct { int full, cw, ch; } Win;
static int screen_w=1728, screen_h=1117, screen_top_inset=32;
static double screen_scale=2;
static int test_px_w, test_px_h, native;
static void cocoa_init(void) {}
static int app_native_fullscreen(void) { return native; }
static int ns_fullscreen(const Win *w) { return w->full; }
static const NSWindowStyleMask windowed_style=NSWindowStyleMaskTitled;
@USER@
static uint32_t modes[6][2];
@MW@
typedef struct { int unused; } Cpu;
static uint32_t selected;
#define M32(a) selected
static int saved;
static int carbon_saved_mode(Cpu *c, uint32_t *slot) { (void)c; *slot=2; return saved; }
static void boot_reg_set_dword(const char *key, uint32_t value) { (void)key; (void)value; }
@CARBON_MODES@
static uint32_t carbon_startup_mode;
static int carbon_startup_selected;
@CARBON_FIRST@
static int failures;
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL %s\n",#x);++failures;}}while(0)
static void check_size(int on, int width, int height, int mw_w, int mw_h, int carbon_slot) {
    if(on) setenv("NFS_FULLSCREEN_NOTCH","1",1); else unsetenv("NFS_FULLSCREEN_NOTCH");
    int w,h; user32_display_pixels(&w,&h);
    CHECK(w==width && h==height);
    build_modes();
    unsigned slot=5;while(slot && !modes[slot][0])--slot;
    CHECK(modes[slot][0]==(uint32_t)mw_w && modes[slot][1]==(uint32_t)mw_h);
    // A fresh process initializes the persistent Carbon table once.
    carbon_modes[5][0]=w;carbon_modes[5][1]=h;
    carbon_startup_selected=0;saved=0;Cpu c={0};carbon_first_mode(&c);
    CHECK(selected==(uint32_t)carbon_slot);
    printf("notch=%d provider=%dx%d MW=%ux%u Carbon=%ux%u slot=%u\n",on,w,h,
           modes[slot][0],modes[slot][1],carbon_modes[selected][0],carbon_modes[selected][1],selected);
    carbon_startup_selected=0;saved=1;carbon_first_mode(&c);CHECK(selected==2);
}
int main(void) { @autoreleasepool {
    screen=[FixtureScreen new];screen.frame=NSMakeRect(0,0,1728,1117);
    screen.visibleFrame=screen.frame;screen.safeAreaInsets=NSEdgeInsetsMake(32,0,0,0);screen.backingScaleFactor=2;
    // Initialize Carbon before the saved-value tests change its state.
    carbon_modes_init();
    check_size(0,3456,2168,3440,2160,3);
    Win window={1,3456,2234};
    CHECK(ns_content_rect(&window).size.height==1085);
    check_size(1,3456,2234,3456,2234,5);
    CHECK(ns_content_rect(&window).size.height==1117);
    setenv("NFS_FULLSCREEN_NOTCH","on",1);CHECK(user32_notch_fill());
    native=1;CHECK(!user32_notch_fill());
    check_size(1,3456,2168,3440,2160,3);native=0;
    screen_w=2560;screen_h=1440;screen_top_inset=0;
    check_size(1,5120,2880,3840,2160,4);
    printf("failures=%d\n",failures);
    return failures?1:0;
} }
'''


def main():
    user = (RT / 'user32.m').read_text()
    user_parts = '\n'.join(function(user, name) for name in
                           ('int user32_notch_fill(', 'static NSRect ns_content_rect(', 'void user32_display_pixels('))
    mw = function((RT / 'widescreen.c').read_text(), 'static void build_modes(')
    provider = (PRIVATE / 'game_mode_provider.h').read_text().split('void widescreen_mode(')[0]
    first = function((PRIVATE / 'game_first_resolution.h').read_text(), 'static void carbon_first_mode(')
    for variant in ('good', 'old-provider', 'old-mw', 'old-carbon'):
        u, m, c = user_parts, mw, first
        if variant == 'old-provider':
            start = u.index('    *h = (int)((screen_h')
            u = u[:start] + '    ' + OLD_PROVIDER.replace('notch_fill()', 'user32_notch_fill()') + '\n}'
        elif variant == 'old-mw':
            start, end = m.index('    // The camera strip'), m.index('    static const uint32_t heights')
            m = m[:start] + '    ' + OLD_MW + '\n' + m[end:]
        elif variant == 'old-carbon':
            start, end = c.index('            int notch_native'), c.index('            if (w*h > area)')
            c = c[:start] + '            ' + OLD_CARBON + '\n' + c[end:]
        source = HARNESS.replace('@USER@', u).replace('@MW@', m).replace('@CARBON_MODES@', provider).replace('@CARBON_FIRST@', c)
        with tempfile.TemporaryDirectory(prefix='notch-') as tmp:
            src, exe = Path(tmp)/'fixture.m', Path(tmp)/'fixture'
            src.write_text(source)
            result = subprocess.run(['clang','-fobjc-arc','-O1','-fsanitize=address,undefined',str(src),
                                     '-framework','Cocoa','-o',str(exe)],capture_output=True,text=True)
            assert result.returncode == 0, result.stderr[-2200:]
            env = {k:v for k,v in os.environ.items() if k not in ('NFS_DISPLAY_PIXELS','NFS_FULLSCREEN_NOTCH')}
            result = subprocess.run([str(exe)],env=env,capture_output=True,text=True)
            assert result.returncode == (0 if variant == 'good' else 1), (variant,result.stdout,result.stderr[-2200:])
            print(variant, 'exit='+str(result.returncode), result.stdout.strip())
    print('NOTCH PASS exact native size, Off/native/saved policy, three original-code controls')


if __name__ == '__main__':
    main()
