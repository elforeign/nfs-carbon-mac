/* Shared port-authored shapes, drawn at half scale for native UI geometry. */
enum { A_CROSS, A_CIRCLE, A_SQUARE, A_TRIANGLE, A_L1, A_R1, A_L2, A_R2, A_R3, A_OPTIONS, A_CREATE, A_DPAD, A_DPAD_DOWN,
       A_DPAD_LEFT, A_DPAD_RIGHT, A_DPAD_LEFTRIGHT, A_RSTICK, A_RSTICK_UP, A_RSTICK_DOWN, A_LSTICK, A_L3, A_DPAD_UP };
#define S 64                               // art size (the FE draws the glyphs at ~32 px per 480 lines)
static void rgb(CGContextRef g, double r, double gg, double b, int fill) {
    if (fill) CGContextSetRGBFillColor(g, r, gg, b, 1); else CGContextSetRGBStrokeColor(g, r, gg, b, 1);
}
static void base_disc(CGContextRef g) {    // a dark round button with a light rim
    rgb(g, 0.10, 0.10, 0.11, 1);
    CGContextFillEllipseInRect(g, CGRectMake(3, 3, S - 6, S - 6));
    CGContextSetLineWidth(g, 2.5);
    rgb(g, 0.62, 0.62, 0.66, 0);
    CGContextStrokeEllipseInRect(g, CGRectMake(3, 3, S - 6, S - 6));
}
static void round_rect(CGContextRef g, CGRect r, double rad, int fill) {
    CGPathRef p = CGPathCreateWithRoundedRect(r, rad, rad, NULL);
    CGContextAddPath(g, p);
    if (fill) CGContextFillPath(g); else CGContextStrokePath(g);
    CGPathRelease(p);
}
static void label(CGContextRef g, const char *text, double size, double cx, double cy) {   // white bold text centred
    CTFontRef font = CTFontCreateUIFontForLanguage(kCTFontUIFontEmphasizedSystem, size, NULL);
    CFStringRef s = CFStringCreateWithCString(NULL, text, kCFStringEncodingUTF8);
    CGColorRef white = CGColorCreateGenericRGB(1, 1, 1, 1);
    const void *k[] = {kCTFontAttributeName, kCTForegroundColorAttributeName}, *v[] = {font, white};
    CFDictionaryRef attr = CFDictionaryCreate(NULL, k, v, 2, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFAttributedStringRef as = CFAttributedStringCreate(NULL, s, attr);
    CTLineRef line = CTLineCreateWithAttributedString(as);
    CGRect b = CTLineGetImageBounds(line, g);
    CGContextSetTextPosition(g, cx - b.origin.x - b.size.width / 2, cy - b.origin.y - b.size.height / 2);
    CTLineDraw(line, g);
    CFRelease(line); CFRelease(as); CFRelease(attr); CGColorRelease(white); CFRelease(s); CFRelease(font);
}
static void shoulder(CGContextRef g, const char *text, int trigger) {   // L1/R1: a bumper; L2/R2: a trigger (taller, rounder)
    CGRect r = trigger ? CGRectMake(6, 6, S - 12, S - 12) : CGRectMake(3, 12, S - 6, S - 24);
    rgb(g, 0.10, 0.10, 0.11, 1);
    round_rect(g, r, trigger ? 16 : 11, 1);
    CGContextSetLineWidth(g, 2.5);
    rgb(g, 0.62, 0.62, 0.66, 0);
    round_rect(g, r, trigger ? 16 : 11, 0);
    label(g, text, 25, S / 2.0, S / 2.0);
}
static void arrow(CGContextRef g, double cx, double cy, double dx, double dy, double size) {   // a filled triangle
    double px = -dy, py = dx;
    CGContextMoveToPoint(g, cx + dx * size, cy + dy * size);
    CGContextAddLineToPoint(g, cx + px * size * 0.8, cy + py * size * 0.8);
    CGContextAddLineToPoint(g, cx - px * size * 0.8, cy - py * size * 0.8);
    CGContextClosePath(g);
    CGContextFillPath(g);
}
static void dpad(CGContextRef g, int up, int down, int left, int right) {   // a D-pad, the named arms lit
    double w = 20, l = S - 8, o = (S - w) / 2;
    rgb(g, 0.10, 0.10, 0.11, 1);
    CGContextFillRect(g, CGRectMake(o - 2, 2, w + 4, l + 4));
    CGContextFillRect(g, CGRectMake(2, o - 2, l + 4, w + 4));
    int lit[4] = {up, down, left, right};
    double ax[4] = {0, 0, -1, 1}, ay[4] = {1, -1, 0, 0};
    for (int i = 0; i < 4; ++i) {
        double cx = S / 2.0 + ax[i] * 19, cy = S / 2.0 + ay[i] * 19;
        if (lit[i]) rgb(g, 0.95, 0.95, 0.95, 1); else rgb(g, 0.38, 0.38, 0.40, 1);
        CGContextFillRect(g, CGRectMake(cx - 8.5, cy - 8.5, 17, 17));
        if (lit[i]) rgb(g, 0.10, 0.10, 0.11, 1); else rgb(g, 0.62, 0.62, 0.66, 1);
        arrow(g, cx, cy, ax[i], ay[i], 6);
    }
    rgb(g, 0.38, 0.38, 0.40, 1);
    CGContextFillRect(g, CGRectMake(o, o, w, w));
}
static void stick(CGContextRef g, const char *text, int up, int down) {   // an analog stick, arrows for the direction
    base_disc(g);
    rgb(g, 0.30, 0.30, 0.32, 1);
    CGContextFillEllipseInRect(g, CGRectMake(15, 15, S - 30, S - 30));
    label(g, text, 20, S / 2.0, S / 2.0);
    rgb(g, 0.95, 0.95, 0.95, 1);
    if (up) arrow(g, S / 2.0, S - 9, 0, 1, 6);
    if (down) arrow(g, S / 2.0, 9, 0, -1, 6);
}
static void draw_art(CGContextRef g, int art) {
    CGContextSetLineCap(g, kCGLineCapRound);
    CGContextSetLineJoin(g, kCGLineJoinRound);
    double c = S / 2.0;
    switch (art) {
    case A_CROSS:                          // the PlayStation colours: blue cross, red circle, pink square, green triangle
        base_disc(g); CGContextSetLineWidth(g, 5.5); rgb(g, 0.49, 0.70, 0.93, 0);
        CGContextMoveToPoint(g, c - 12, c - 12); CGContextAddLineToPoint(g, c + 12, c + 12);
        CGContextMoveToPoint(g, c - 12, c + 12); CGContextAddLineToPoint(g, c + 12, c - 12);
        CGContextStrokePath(g); break;
    case A_CIRCLE:
        base_disc(g); CGContextSetLineWidth(g, 5.5); rgb(g, 0.96, 0.42, 0.44, 0);
        CGContextStrokeEllipseInRect(g, CGRectMake(c - 14, c - 14, 28, 28)); break;
    case A_SQUARE:
        base_disc(g); CGContextSetLineWidth(g, 5.5); rgb(g, 0.89, 0.55, 0.84, 0);
        CGContextStrokeRect(g, CGRectMake(c - 12.5, c - 12.5, 25, 25)); break;
    case A_TRIANGLE:
        base_disc(g); CGContextSetLineWidth(g, 5.5); rgb(g, 0.25, 0.84, 0.66, 0);
        CGContextMoveToPoint(g, c, c + 15); CGContextAddLineToPoint(g, c + 14.5, c - 10);
        CGContextAddLineToPoint(g, c - 14.5, c - 10); CGContextClosePath(g); CGContextStrokePath(g); break;
    case A_L1: shoulder(g, "L1", 0); break;
    case A_R1: shoulder(g, "R1", 0); break;
    case A_L2: shoulder(g, "L2", 1); break;
    case A_R2: shoulder(g, "R2", 1); break;
    case A_L3: stick(g, "L3", 0, 0); break;
    case A_R3: stick(g, "R3", 0, 0); break;
    case A_OPTIONS:                        // the DualSense Options button: a small pill, three lines
    case A_CREATE: {                       // Create: the same pill, its three-ray mark
        CGRect r = CGRectMake(14, 4, S - 28, S - 8);
        rgb(g, 0.10, 0.10, 0.11, 1); round_rect(g, r, 13, 1);
        CGContextSetLineWidth(g, 2.5); rgb(g, 0.62, 0.62, 0.66, 0); round_rect(g, r, 13, 0);
        CGContextSetLineWidth(g, 4); rgb(g, 0.95, 0.95, 0.95, 0);
        if (art == A_OPTIONS)
            for (int i = -1; i <= 1; ++i) { CGContextMoveToPoint(g, c - 8, c + i * 9); CGContextAddLineToPoint(g, c + 8, c + i * 9); }
        else
            for (int i = -1; i <= 1; ++i) {
                double a = M_PI / 2 + i * 0.7;    // three separate dashes fanning out upwards
                CGContextMoveToPoint(g, c + cos(a) * 9, c - 11 + sin(a) * 9);
                CGContextAddLineToPoint(g, c + cos(a) * 20, c - 11 + sin(a) * 20);
            }
        CGContextStrokePath(g); break;
    }
    case A_DPAD: dpad(g, 1, 1, 1, 1); break;
    case A_DPAD_UP: dpad(g, 1, 0, 0, 0); break;
    case A_DPAD_DOWN: dpad(g, 0, 1, 0, 0); break;
    case A_DPAD_LEFT: dpad(g, 0, 0, 1, 0); break;
    case A_DPAD_RIGHT: dpad(g, 0, 0, 0, 1); break;
    case A_DPAD_LEFTRIGHT: dpad(g, 0, 0, 1, 1); break;
    case A_RSTICK: stick(g, "R", 0, 0); break;
    case A_RSTICK_UP: stick(g, "R", 1, 0); break;
    case A_RSTICK_DOWN: stick(g, "R", 0, 1); break;
    case A_LSTICK: stick(g, "L", 0, 0); break;
    }
}
