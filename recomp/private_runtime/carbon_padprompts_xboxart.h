/* Port-authored Xbox art uses the shared renderer's drawing spec.
 * Native prompt names use L1/R1 for bumpers, L2/R2 for triggers. */
static int xbox_prompt_art(void) {
    const char *e=getenv("NFS_XBOX_PROMPT_ART");
    return !(e && (!strcasecmp(e,"off") || !strcmp(e,"0")));
}
static void draw_xbox_art(CGContextRef g, const char *xb) {
    if (!strcmp(xb, "L1_LOADING")) xb="L1";
    if (!strcmp(xb, "R1_LOADING")) xb="R1";
    const char *face = NULL;
    double r = 0, green = 0, b = 0;
    if (!strcmp(xb, "CROSS")) { face = "A"; r = 0.15; green = 0.68; b = 0.25; }
    else if (!strcmp(xb, "TRIANGLE")) { face = "B"; r = 0.85; green = 0.16; b = 0.16; }
    else if (!strcmp(xb, "SQUARE")) { face = "X"; r = 0.12; green = 0.42; b = 0.86; }
    else if (!strcmp(xb, "CIRCLE")) { face = "Y"; r = 0.86; green = 0.67; b = 0.08; }
    if (face) {
        base_disc(g);
        rgb(g, r, green, b, 1);
        CGContextFillEllipseInRect(g, CGRectMake(6, 6, S - 12, S - 12));
        label(g, face, 36, S / 2.0, S / 2.0);
    } else if (!strcmp(xb, "L1")) shoulder(g, "LB", 0);
    else if (!strcmp(xb, "R1")) shoulder(g, "RB", 0);
    else if (!strcmp(xb, "L2")) shoulder(g, "LT", 1);
    else if (!strcmp(xb, "R2")) shoulder(g, "RT", 1);
    else if (!strcmp(xb, "START")) {
        base_disc(g);
        CGContextSetLineWidth(g, 3);
        rgb(g, 0.95, 0.95, 0.95, 0);
        for (int y = 23; y <= 41; y += 9) {
            CGContextMoveToPoint(g, 20, y); CGContextAddLineToPoint(g, 44, y);
        }
        CGContextStrokePath(g);
    } else if (!strcmp(xb, "SELECT")) {
        base_disc(g);
        CGContextSetLineWidth(g, 3);
        rgb(g, 0.95, 0.95, 0.95, 0);
        CGContextStrokeRect(g, CGRectMake(18, 28, 20, 16));
        CGContextStrokeRect(g, CGRectMake(26, 20, 20, 16));
    } else if (!strcmp(xb, "R3")) {
        stick(g, "RS", 0, 0);
        rgb(g, 0.95, 0.95, 0.95, 0); CGContextSetLineWidth(g, 2);
        CGContextStrokeEllipseInRect(g, CGRectMake(10, 10, S - 20, S - 20));
    } else if (!strcmp(xb, "L3")) {
        stick(g, "LS", 0, 0);
        rgb(g, 0.95, 0.95, 0.95, 0); CGContextSetLineWidth(g, 2);
        CGContextStrokeEllipseInRect(g, CGRectMake(10, 10, S - 20, S - 20));
    } else if (!strcmp(xb, "RIGHT_ANALOG")) stick(g, "RS", 0, 0);
    else if (!strcmp(xb, "RIGHT_ANALOG_UP")) stick(g, "RS", 1, 0);
    else if (!strcmp(xb, "RIGHT_ANALOG_DOWN")) stick(g, "RS", 0, 1);
    else if (!strcmp(xb, "LEFT_ANALOG")) stick(g, "LS", 0, 0);
    else if (!strcmp(xb, "DPAD")) dpad(g, 1, 1, 1, 1);
    else if (!strcmp(xb, "DPAD_UP")) dpad(g, 1, 0, 0, 0);
    else if (!strcmp(xb, "DPAD_DOWN")) dpad(g, 0, 1, 0, 0);
    else if (!strcmp(xb, "DPAD_LEFT")) dpad(g, 0, 0, 1, 0);
    else if (!strcmp(xb, "DPAD_RIGHT")) dpad(g, 0, 0, 0, 1);
    else if (!strcmp(xb, "DPAD_LEFTRIGHT")) dpad(g, 0, 0, 1, 1);
}
