/* The C3 test driver shares the simulated pad's pressure/filter path. */
extern int carbon_c3drive_pad(int, float *, float *, float *);
if (!idx && sim && !strncmp(sim,"sim:",4)) {
    if (carbon_c3drive_pad(idx,&st->lx,&st->rt,&st->lt)==2) [NSApp terminate:nil];
}
/* Apply scripted pressures before filtering, just as physical pressures are. */
for (int k = 4; k < 6; ++k) if (axis[0] && !strncmp(axis, an[k], 2)) *ax[k] = axv;
carbon_pad_deliver(idx, st, st->buttons);
st->buttons |= idx ? script_raw2 : script_raw;
