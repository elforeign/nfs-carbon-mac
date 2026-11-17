#import <Cocoa/Cocoa.h>
#include "carbon_pad_layout.h"
@interface CarbonLayoutMenu : NSObject <NSMenuItemValidation>
@end
@implementation CarbonLayoutMenu
- (void)choose:(NSMenuItem *)item { carbon_pad_layout_set((int)item.tag); }
- (void)automatic:(id)sender { (void)sender; carbon_pad_layout_reset(); }
- (BOOL)validateMenuItem:(NSMenuItem *)item {
    if (item.action == @selector(choose:)) item.state = item.tag == carbon_pad_layout_get() ? NSControlStateValueOn : NSControlStateValueOff;
    if (item.action == @selector(automatic:)) {
        char reason[128]; carbon_pad_layout_reason(reason,sizeof reason);
        item.title = [NSString stringWithFormat:@"%s (Reset preference)",reason];
    }
    return YES;
}
@end
void carbon_pad_layout_menu_init(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        static CarbonLayoutMenu *target;
        if (!target) target = [CarbonLayoutMenu new];
        NSMenu *menu = [NSApp.mainMenu itemWithTitle:@"Controller"].submenu;
        if (!menu) return;
        [menu removeAllItems];
        NSArray<NSString *> *names = @[@"PlayStation", @"Xbox", @"PC"];
        for (NSInteger i = 0; i < 3; ++i) {
            NSMenuItem *item = [menu addItemWithTitle:names[i] action:@selector(choose:) keyEquivalent:@""];
            item.target = target; item.tag = i;
        }
        NSMenuItem *reset = [menu addItemWithTitle:@"Automatic (Reset)" action:@selector(automatic:) keyEquivalent:@""];
        reset.target = target;
    });
}
