"""Explicit host source ownership and the reviewed disabled-feature boundary."""
import json
import ast
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
from quarantine import audit_tree

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'runtime/runtime_sources.json'
EXPORTS = Path(__file__).with_name('disabled_exports.json')
BINDINGS = Path(__file__).with_name('bindings.json')
FEATURES = Path(__file__).with_name('features')
# These console-derived inputs are deliberately absent from public source exports.
OPTIONAL_INCLUDES = frozenset({'carbon_padbind_ps3.inc', 'carbon_padbind_x360.inc',
                               'carbon_worldreflect_shader.inc', 'world_probe.inc'})


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('duplicate JSON name: ' + name)
        result[name] = value
    return result


def _merge_features(data, directory, private_runtime, bindings, exports, image_sha256):
    """Extend only the private target; keep provenance for fail-closed diagnostics."""
    target = data['targets']['private']
    registry = {'directory': str(private_runtime), 'bindings': bindings,
                'exports': exports, 'all_exports': exports,
                'enabled_providers': {}, 'source_files': {}}
    data['_private_registry'] = registry
    occupied = (set(data['sources']) | set(target['extra_sources']) |
                set(target['staged_sources']) | set(target['extra_units']) |
                set(bindings['sources']))
    originals = {(private_runtime / value).resolve() for value in target['staged_sources'].values()}
    disabled = {row['name'] for row in exports}
    for path in sorted(Path(directory).glob('*.json')):
        try:
            feature = json.loads(path.read_text(), object_pairs_hook=_unique_object)
            fields = {'version', 'target', 'image_sha256', 'sources',
                      'staged_sources', 'bindings', 'enabled_providers'}
            if set(feature) != fields or type(feature['version']) is not int or feature['version'] != 1 or feature['target'] != 'private':
                raise ValueError('expected version 1 private feature fields')
            digest = feature['image_sha256']
            if (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or
                    digest != bindings['image_sha256'] or
                    (image_sha256 is not None and digest != image_sha256)):
                raise ValueError('feature image digest differs')
            sources = feature['sources']
            staged = feature['staged_sources']
            if (not all(isinstance(v, dict) for v in (sources, staged, feature['bindings'])) or
                    not isinstance(feature['enabled_providers'], list) or
                    set(sources) != set(staged) or set(sources) != set(feature['bindings'])):
                raise ValueError('sources, staged_sources and bindings must name the same sources')
            for name, row in sources.items():
                if not re.fullmatch(r'[A-Za-z_]\w*\.(?:c|m|mm|cpp|h|inc)', name):
                    raise ValueError('invalid staged source name: ' + name)
                if name in occupied:
                    raise ValueError('duplicate source: ' + name)
                if (row['targets'] != ['private'] or row['class'] not in ('shared', 'mixed') or
                        row['kind'] not in ('unit', 'include') or
                        row['constructors'] not in ('forbidden', 'allowed') or
                        (row['kind'] == 'unit' and Path(name).suffix not in ('.c', '.m', '.mm', '.cpp'))):
                    raise ValueError('invalid private source policy: ' + name)
                original = staged[name]
                canonical = (private_runtime / original).resolve()
                if original in OPTIONAL_INCLUDES and name == original and not canonical.exists():
                    continue
                if (Path(original).is_absolute() or not canonical.is_relative_to(private_runtime.resolve()) or
                        not canonical.is_file()):
                    raise ValueError('invalid private source path: ' + original)
                if canonical in originals:
                    raise ValueError('duplicate canonical source: ' + original)
                entry = feature['bindings'][name]
                if (entry['source'] != original or
                        entry['sha256'] != hashlib.sha256(canonical.read_bytes()).hexdigest()):
                    raise ValueError('source digest differs: ' + name)
                if not isinstance(entry['functions'], dict):
                    raise ValueError('invalid binding functions: ' + name)
                for function, accesses in entry['functions'].items():
                    if (not re.fullmatch(r'[A-Za-z_]\w*', function) or
                            not isinstance(accesses, dict) or set(accesses) - {'read', 'write'}):
                        raise ValueError('invalid binding function/access: ' + name)
                    for addresses in accesses.values():
                        if (not isinstance(addresses, list) or len(addresses) != len(set(addresses)) or
                                any(type(a) is not int or not 0 <= a <= 0xffffffff for a in addresses)):
                            raise ValueError('invalid binding addresses: ' + name)
                occupied.add(name)
                originals.add(canonical)
                target['extra_sources'][name] = row
                target['staged_sources'][name] = original
                if row['kind'] == 'unit':
                    target['extra_units'].append(name)
                bindings['sources'][name] = entry
                registry['source_files'][name] = str(path)
            for name in feature['enabled_providers']:
                if name not in disabled:
                    raise ValueError('unknown disabled provider: ' + str(name))
                if name in registry['enabled_providers']:
                    raise ValueError('duplicate enabled provider: ' + name)
                registry['enabled_providers'][name] = str(path)
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise ValueError(f'{path}: {error}') from error
    registry['exports'] = [row for row in exports if row['name'] not in registry['enabled_providers']]


def declared_accesses(manifest):
    bindings = manifest.get('_private_registry', {}).get('bindings') or json.loads(BINDINGS.read_text())
    return {(source, function, access, address)
            for source, entry in bindings['sources'].items()
            for function, accesses in entry['functions'].items()
            for access, addresses in accesses.items() for address in addresses}


def disabled_exports(manifest=None):
    if manifest and '_private_registry' in manifest:
        return manifest['_private_registry']['exports']
    return json.loads(EXPORTS.read_text())


def production_sources(runtime):
    return {p.name for p in runtime.iterdir()
            if p.suffix in ('.c', '.m', '.mm', '.cpp', '.h', '.inc')
            and not re.search(r'(^test_|_test(?:\.|_))', p.name)}


def load_manifest(path=MANIFEST, runtime=None, *, features=FEATURES,
                  private_runtime=None, bindings=BINDINGS, exports=EXPORTS,
                  image_sha256=None):
    data = json.loads(Path(path).read_text())
    runtime = Path(runtime) if runtime else ROOT / 'runtime'
    missing = production_sources(runtime) - data['sources'].keys()
    if missing:
        raise ValueError('unclassified runtime source: ' + ', '.join(sorted(missing)))
    for name, row in data['sources'].items():
        if row['class'] not in ('shared', 'mw', 'mixed'):
            raise ValueError('invalid source class: ' + name)
        if row['constructors'] not in ('forbidden', 'allowed'):
            raise ValueError('invalid constructor policy: ' + name)
        if 'private' in row['targets'] and row['class'] == 'mw':
            raise ValueError('MW source selected for private target: ' + name)
    selected = data['targets']['private']['units']
    expected = {n for n, r in data['sources'].items()
                if r['kind'] == 'unit' and 'private' in r['targets']}
    if set(selected) != expected or len(selected) != len(set(selected)):
        raise ValueError('private source membership differs from ownership manifest')
    _merge_features(data, features, Path(private_runtime) if private_runtime else Path(__file__).parent,
                    json.loads(Path(bindings).read_text()), json.loads(Path(exports).read_text()),
                    image_sha256)
    return data


def _disabled_bytes(manifest=None):
    registry = (manifest or {}).get('_private_registry', {})
    source = Path(registry.get('directory', Path(__file__).parent)) / 'disabled_providers.m'
    enabled = registry.get('enabled_providers', {})
    if not enabled:
        return source.read_bytes()
    # The reviewed file has one typed definition per origin-comment block.
    # Refuse an unfamiliar layout rather than risk dropping a second definition.
    blocks = re.split(r'(?m)(?=^/\* [^\n]* \*/$)', source.read_text())
    inventory = {row['name'] for row in registry.get('all_exports', json.loads(EXPORTS.read_text()))}
    removed = set()
    retained = []
    for block in blocks:
        names = {name for name in inventory if re.search(r'\b' + re.escape(name) + r'\s*(?:\(|\[|=|;)', block)}
        selected = names & enabled.keys()
        if selected:
            if len(names) != 1 or selected & removed:
                name = sorted(selected)[0]
                raise ValueError(f'{enabled[name]}: ambiguous disabled definition: {name}')
            removed.update(selected)
        else:
            retained.append(block)
    if removed != enabled.keys():
        name = sorted(enabled.keys() - removed)[0]
        raise ValueError(f'{enabled[name]}: disabled definition absent: {name}')
    return ''.join(retained).encode()


def stage_disabled(dst, manifest=None):
    """Generate one selected TU from a fixed, reviewed typed implementation."""
    (dst / 'disabled_providers.m').write_bytes(_disabled_bytes(manifest))
    return 'disabled_providers.m'


def stage_sources(dst, manifest):
    directory = Path(manifest['_private_registry']['directory'])
    for name in OPTIONAL_INCLUDES:
        if not (directory / name).exists():
            (dst / name).unlink(missing_ok=True)
    for selected, original in manifest['targets']['private']['staged_sources'].items():
        if original in OPTIONAL_INCLUDES and not (directory / original).exists():
            (dst / selected).unlink(missing_ok=True)
            continue
        shutil.copy2(directory / original, dst / selected)
    stage_disabled(dst, manifest)


def symbols(objects, flag):
    if not objects:
        return set()
    result = subprocess.run(['nm', flag, *map(str, objects)],
                            capture_output=True, text=True, check=True)
    return set(re.findall(r'^\s*(?:[0-9a-f]+\s+[A-Za-z]\s+)?(_\w+)\s*$',
                          result.stdout, re.M))


def check_disabled_boundary(objects, provider, manifest=None):
    declared = {'_' + row['name'] for row in disabled_exports(manifest)}
    defined = symbols([provider], '-gU')
    if declared != defined:
        raise ValueError('disabled provider exports differ from reviewed inventory: ' +
                         repr(sorted(declared ^ defined)))
    required = symbols(objects, '-u') - symbols(objects, '-gU')
    # A host dependency outside the declared boundary must fail at link time.
    # This comparison also detects stale provider entries and changed selection.
    used = required & defined
    if used != declared:
        raise ValueError('disabled provider boundary changed: ' +
                         repr(sorted(declared - used)))
    real = symbols(objects, '-gU')
    for name, file in (manifest or {}).get('_private_registry', {}).get('enabled_providers', {}).items():
        if '_' + name not in real:
            raise ValueError(f'{file}: enabled provider has no real definition: {name}')
    return len(declared)


def audit_unit(path, flags, ranges):
    """Audit a real preprocessed TU, retaining #line origins from every include."""
    path = Path(path)
    expanded = path.with_name(path.name + '.preprocessed')
    result = subprocess.run(['clang', *flags, '-E', str(path), '-o', str(expanded)],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    language = {'.c': 'cpp-output', '.m': 'objective-c-cpp-output',
                '.mm': 'objective-c++-cpp-output', '.cpp': 'c++-cpp-output'}[path.suffix]
    result = subprocess.run(['clang', '-w', '-fobjc-arc', '-x', language,
                             '-fsyntax-only', '-Xclang', '-ast-dump=json', str(expanded)],
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode()[-2000:])
    rows = audit_tree(json.loads(result.stdout), ranges)
    # Preprocessor flag 3 marks system headers. Follow every other include,
    # including absolute/parent paths, apart from the guest support boundary.
    origins = set()
    for name, marker_flags in re.findall(r'^#\s+\d+\s+"([^"\n]+)"([^\n]*)',
                                         expanded.read_text(), re.M):
        if name.startswith('<') or '3' in marker_flags.split():
            continue
        origin = Path(name).resolve()
        if origin == ROOT / 'recomp/runtime.h' or (origin.name == 'funcs.h' and
                                                  origin.is_relative_to(ROOT / 'recomp/out')):
            continue
        origins.add(str(origin))
    host = [row for row in rows if str(Path(row['source']).resolve()) in origins]
    image_path = path.parent.parent / 'image.json'
    image_sha = json.loads(image_path.read_text())['sha256'] if image_path.is_file() else None
    return {'unit': path.name, 'origins': sorted(origins), 'declarations': host,
            'image_sha256': image_sha}


def build_owned(out):
    """True when the build outputs in `out` were linked from this folder's own guest archive. A new worktree starts
    with build outputs cloned from another checkout; their audits describe that checkout's sources, not this one's."""
    out = Path(out)
    if not (out / 'link_command.json').is_file():
        return False
    command = json.loads((out / 'link_command.json').read_text())
    return [Path(arg).resolve() for arg in command if arg.endswith('/NFSC.a')] == [(out / 'NFSC.a').resolve()]


def check_audits(audits, manifest, extra_sources=(), *, require_complete=False):
    """Fail on addresses, included implementations, constructors and callbacks."""
    problems = []
    rows = [row for unit in audits for row in unit['declarations']]
    policies = {}
    registry = manifest.get('_private_registry', {})
    bindings = registry.get('bindings') or json.loads(BINDINGS.read_text())
    private_accesses = set()
    effective_accesses = {}
    for unit in audits:
        for row in unit['declarations']:
            accesses = row['accesses']
            entry = bindings['sources'].get(Path(row['source']).name)
            if entry and accesses:
                canonical = Path(registry.get('directory', Path(__file__).parent)) / entry['source']
                source = Path(row['source'])
                if (unit.get('image_sha256') != bindings['image_sha256'] or
                        hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256'] or
                        hashlib.sha256(canonical.read_bytes()).hexdigest() != entry['sha256']):
                    problems.append('private binding image/source digest differs: ' + source.name +
                                    ' ' + registry.get('source_files', {}).get(source.name, ''))
                else:
                    allowed = entry['functions'].get(row['name'], {})
                    retained = []
                    for access, address in accesses:
                        if address in allowed.get(access, []):
                            private_accesses.add((source.name, row['name'], access, address))
                        else:
                            retained.append((access, address))
                    accesses = retained
            effective_accesses[id(row)] = accesses
    extra_sources = set(extra_sources)
    for unit in audits:
        # Cloned build audits retain their producer's absolute checkout paths.
        # Locate that root from the staged translation unit, never from a
        # header basename: external include policies are checkout-relative.
        roots = {p.parents[4] for origin in unit['origins']
                 if (p := Path(origin)).name == unit['unit']
                 and len(p.parents) > 4 and p.parent.name == 'runtime'
                 and p.parents[2].name == 'out' and p.parents[3].name == 'recomp'}
        source_root = next(iter(roots)) if len(roots) == 1 else ROOT
        for origin in unit['origins']:
            name = Path(origin).name
            file = Path(origin)
            external = (manifest.get('external_includes', {}).get(str(file.relative_to(source_root)))
                        if file.is_relative_to(source_root) else None)
            policy = external or manifest['targets']['private'].get('extra_sources', {}).get(
                name, manifest['sources'].get(name, {}))
            policies[origin] = policy
            if not policy and name not in extra_sources:
                # Generated data is separately owned and remains MW-specific;
                # its use by the temporary compatibility renderer is explicit.
                if '/gen/' not in origin or not name.endswith('.inc'):
                    problems.append('unclassified included source: ' + origin)
    for row in rows:
        name = row['name']; source = Path(row['source']).name
        policy = policies.get(str(Path(row['source']).resolve()), {})
        if re.fullmatch(r'mw_f_[0-9A-Fa-f]{8}(?:_orig)?', name):
            problems.append('engine implementation selected: ' + source + '::' + name)
        if re.fullmatch(r'f_[0-9A-Fa-f]{8}(?:_orig)?', name):
            problems.append('guest-symbol collision: ' + name)
        if row['constructor'] and (policy.get('constructors') != 'allowed' or
                                   name not in policy.get('constructor_symbols', [])):
            problems.append('forbidden constructor: ' + source + '::' + name)
        if row['kind'] == 'function' and policy.get('class') == 'mw':
            problems.append('included MW implementation: ' + source + '::' + name)
        for access, address in effective_accesses[id(row)]:
            owner = registry.get('source_files', {}).get(source)
            problems.append(f'MW address {access}: {source}::{name} 0x{address:08X}' +
                            (f' ({owner})' if owner else ''))
    unsafe = {row['name'] for row in rows if effective_accesses[id(row)]}
    while True:
        more = {row['name'] for row in rows
                if set(row['calls'] + row['references']) & unsafe} - unsafe
        if not more:
            break
        unsafe.update(more)
    # Calls and setting callback initializers cross translation-unit boundaries.
    for row in rows:
        bad = set(row['calls'] + row['references']) & unsafe
        if bad and not effective_accesses[id(row)]:
            problems.append('MW provider dependency: ' + row['name'] + ' -> ' + ', '.join(sorted(bad)))
    if require_complete and private_accesses != declared_accesses(manifest):
        problems.append('approved private accesses differ from declarations: ' +
                        repr(sorted(private_accesses ^ declared_accesses(manifest))))
    problems = sorted(set(problems))
    if problems:
        raise ValueError('\n'.join(problems))
    return {'translation_units': len(audits), 'MW_reads': 0, 'MW_writes': 0,
            'forbidden_constructors': 0, 'guest_collisions': 0,
            'private_binding_accesses': len(private_accesses)}


def selected_source(path):
    """Fixture view of the selected source, preserving API/memory macros.

    Production staging never uses this: fixtures need included policy bodies
    to make their existing mutations after compile-time game selection.
    """
    path = Path(path)
    staged = load_manifest()['targets']['private']['staged_sources']
    def expand(source):
        result = subprocess.run(['unifdef', '-DNFS_GAME=2', '-DNFS_GAME_MW=1',
                                 '-DNFS_GAME_PRIVATE=2'], input=source,
                                capture_output=True, text=True)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        source = result.stdout
        def include(match):
            name = match[1]
            if name not in staged:
                return match[0]
            included = path.parent / name
            if not included.is_file():
                original = staged[name]
                included = Path(__file__).with_name(original)
            return expand(included.read_text())
        return re.sub(r'^#include "(game_\w+\.(?:h|inc))"[^\n]*', include, source, flags=re.M)
    return expand(path.read_text())


def audit_preparations(overrides=None):
    """No production preparation entry point may return after this migration."""
    paths = ['private_render.py', 'private_frontend.py', 'private_positiont.py',
             'build_private_runtime.py']
    for name in paths:
        source = (overrides or {}).get(name)
        if source is None:
            source = (ROOT / 'recomp' / name).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('prepare_'):
                raise ValueError('production rewrite entry point: ' + name + '::' + node.name)
            if isinstance(node, ast.Call):
                call = node.func
                label = call.id if isinstance(call, ast.Name) else call.attr if isinstance(call, ast.Attribute) else ''
                if label in ('prepare_renderer', 'prepare_frontend', 'prepare_positiont', 'replace', 'replace_body', 'remove_branch', 'once'):
                    raise ValueError('production rewrite call: ' + name + '::' + label)


def verify_staged(dst, manifest):
    """Compare every staged production source with its canonical tree bytes."""
    dst = Path(dst)
    originals = {p.name: p for p in (ROOT / 'runtime').iterdir()
                 if p.suffix in ('.c', '.m', '.mm', '.cpp', '.h', '.inc')}
    directory = Path(manifest.get('_private_registry', {}).get('directory', Path(__file__).parent))
    originals.update({selected: directory / original
                      for selected, original in manifest['targets']['private']['staged_sources'].items()
                      if original not in OPTIONAL_INCLUDES or (directory / original).exists()})
    # The selected import table is generated from this image, not the MW table.
    originals['imports.c'] = dst.parent / 'imports.c'
    differing = [name for name, original in originals.items()
                 if (dst / name).read_bytes() != (_disabled_bytes(manifest) if name == 'disabled_providers.m'
                                                else original.read_bytes())]
    if differing:
        raise ValueError('staged source differs: ' + ', '.join(differing))
    proof = {'compared': len(originals), 'differing': 0}
    (dst.parent / 'runtime_staging.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof
