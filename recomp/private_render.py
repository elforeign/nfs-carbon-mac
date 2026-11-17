"""Renderer fixture extraction and required-body audit.

Production source selection is compile-time only; these parsing helpers serve tests.
"""
import re


def closing_brace(source, begin):
    """C/Objective-C brace matching, skipping comments and string/char literals."""
    depth=0;i=begin
    while i<len(source):
        if source.startswith('//',i):
            e=source.find('\n',i);i=len(source) if e<0 else e+1;continue
        if source.startswith('/*',i):
            e=source.find('*/',i+2)
            if e<0:raise ValueError('unterminated comment')
            i=e+2;continue
        c=source[i]
        if c in ('"',"'"):
            q=c;i+=1
            while i<len(source):
                if source[i]=='\\':i+=2;continue
                if source[i]==q:i+=1;break
                i+=1
            continue
        if c=='{':depth+=1
        elif c=='}':
            depth-=1
            if depth==0:return i
        i+=1
    raise ValueError('unterminated function')


def function_span(source,name):
    matches=list(re.finditer(r'\b'+re.escape(name)+r'\s*\([^;{}]*?\)\s*\{',source))
    if len(matches)!=1:raise ValueError(f'expected one function body: {name}, found {len(matches)}')
    begin=source.index('{',matches[0].start(),matches[0].end())
    return begin,closing_brace(source,begin)+1


def body(source,name):
    a,b=function_span(source,name);return source[a:b]


def replace_body(source,name,replacement):
    a,b=function_span(source,name);return source[:a]+replacement+source[b:]


REQUIRED={'pipeline_cache.m':{'pipeline_library_source','pipeline_build_device','pipeline_build','pipeline_cached','pipeline_cached_library','pipeline_register_shader'},
          'd3d9.m':{'d_CreateDevice','v_Present','present','v_Clear','v_DrawPrimitive','v_DrawIndexedPrimitive','v_DrawPrimitiveUP','v_DrawIndexedPrimitiveUP','v_CreateTexture','v_CreateVertexShader','v_CreatePixelShader','private_d3dx_textures','px_create','px_dds','px_fill','px_load','px_serialize','px_buffer','px_save_file'},
          'render.m':{'render_init','render_resize','get_shader_variant','render_draw','draw_impl','render_stretch','ff_shaders','compile_entry','gpu_tex','gpu_buf','private_surface_readback','private_surface_upload','private_up_summary'},
          'render_present.m':{'render_present','present_copy','present_show','png_after'},
          'diag.c':{'diag_png','diag_shot_due','diag_frame_wanted','diag_frame'}}


def verify_renderer(inventory):
    for filename,required in REQUIRED.items():
        rows=inventory[filename]
        lost=required & {row['name'] for row in rows if row['reason'] not in ('private diagnostics',)}
        if lost:raise ValueError(f'private renderer quarantined required bodies in {filename}: {sorted(lost)}')
