/* Receiver coverage of additive glows (SRCALPHA/ONE: reflector and street-lamp flares,
 * world light cards). Many carry opaque alpha over the whole quad and draw their shape in
 * colour, so coverage by alpha alone protected the whole quad: lamp pools and contact
 * shading cut a hard square out of the road around every reflector. Coverage is what the
 * draw adds, saturate(max(rgb) * alpha): the black surround stays a receiver, the bright
 * core stays protected. The variant patches the translated pixel shader's single colour
 * output (after its alpha test, which still uses the draw's own alpha). */
enum { MAT_VARIANT_AO_GLOW = 0x112 };
static char *carbon_ao_glow_shader(const char *msl) {
    static const char out[]="    r.c0 = so.oc[0];\n";
    static const char add[]="    r.c0.a = saturate(max(max(r.c0.r, r.c0.g), r.c0.b) * r.c0.a);\n";
    const char *at=msl?strstr(msl,out):NULL;
    if(!at || strstr(at+1,out))return NULL; // exactly one colour output, else keep coverage by alpha
    size_t head=(size_t)(at-msl)+sizeof out-1,n=strlen(msl);
    char *s=malloc(n+sizeof add);
    if(!s)return NULL;
    memcpy(s,msl,head);memcpy(s+head,add,sizeof add-1);memcpy(s+head+sizeof add-1,msl+head,n-head+1);
    return s;
}
