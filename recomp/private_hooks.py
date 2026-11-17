"""Image-bound declarations and emission for private guest hooks."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

REGISTRY = Path(__file__).resolve().parent / 'private_runtime' / 'hooks'


def load_registry(pe, functions, directory=None):
    """Validate every record before generation; an empty directory changes no C."""
    directory = Path(directory) if directory is not None else REGISTRY
    if not directory.is_dir():
        raise ValueError(f'private hook registry missing: {directory}')
    limits = {a: end for a, end, _ in functions}
    hooks = {}
    for path in sorted(directory.glob('*.json')):
        try:
            manifest = json.loads(path.read_text())
            if (set(manifest) != {'version', 'hooks'} or type(manifest['version']) is not int
                    or manifest['version'] != 1 or not isinstance(manifest['hooks'], list)):
                raise ValueError('expected version=1 and hooks list')
        except (ValueError, TypeError) as error:
            raise ValueError(f'{path.name}: {error}') from error
        for index, record in enumerate(manifest['hooks']):
            label = f'{path.name}:hooks[{index}]'
            try:
                if set(record) != {'address', 'image_sha256', 'witness', 'provider', 'job'}:
                    raise ValueError('expected address, image_sha256, witness, provider, job')
                address = record['address']
                if not isinstance(address, str) or not re.fullmatch(r'[0-9A-F]{8}', address):
                    raise ValueError('address must be eight uppercase hex digits')
                label += f' {address}'
                address = int(address, 16)
                if record['image_sha256'] != pe.sha256:
                    raise ValueError('image SHA-256 mismatch')
                if address not in limits:
                    raise ValueError('address is not a function start')
                if address in hooks:
                    raise ValueError(f'duplicate address; first record {hooks[address]["record"]}')
                provider = record['provider']
                if not isinstance(provider, str) or not re.fullmatch(r'carbon_(?!orig_)[A-Za-z0-9_]+', provider):
                    raise ValueError('provider must be a named carbon_ function (not carbon_orig_)')
                if not isinstance(record['job'], str) or not record['job'].strip():
                    raise ValueError('job must name the owning job')
                witness = record['witness']
                if set(witness) != {'start', 'length', 'sha256'}:
                    raise ValueError('witness requires start, length, sha256')
                if witness['start'] != record['address']:
                    raise ValueError('witness must start at the function entry')
                length = witness['length']
                if type(length) is not int or not 1 <= length <= limits[address] - address:
                    raise ValueError('witness length outside function')
                digest = witness['sha256']
                if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                    raise ValueError('invalid witness SHA-256')
                raw = pe.read(address, length)
                if raw is None or len(raw) != length or hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError('original-byte witness mismatch')
                hooks[address] = dict(record, record=label)
            except (ValueError, TypeError, KeyError) as error:
                raise ValueError(f'{label}: {error}') from error
    return hooks


def original_name(address):
    return f'carbon_orig_{address:08X}'


def wrap(address, code, record):
    """Rename only the definition; every guest call still names the wrapper."""
    original = original_name(address)
    code, count = re.subn(rf'\bvoid f_{address:08X}(\(Cpu \*(?:restrict )?c\)\s*\{{)',
                          rf'void {original}\1', code, count=1)
    if count != 1 or 'untranslated(c,' in code:
        raise ValueError(f'{record["record"]}: original body is unavailable')
    return code + (f'\n__attribute__((noinline)) void f_{address:08X}(Cpu *c) '
                   f'{{ {record["provider"]}(c, {original}); }}')


def declarations(hooks):
    return ''.join(f'void {original_name(a)}(Cpu *c);\n'
                   f'void {r["provider"]}(Cpu *c, void (*original)(Cpu *));\n'
                   for a, r in sorted(hooks.items()))


def check_providers(hooks, objects, archive=None):
    """Require real runtime definitions and the generated archive's identities."""
    if not hooks:
        return
    def symbols(paths, option):
        return subprocess.run(['nm', option, *map(str, paths)], check=True,
                              capture_output=True, text=True).stdout
    defined = symbols(objects, '-gU') if objects else ''
    names = set(re.findall(r'^.*\bT _?(\w+)\s*$', defined, re.M))
    guest = symbols([archive], '-gU') if archive is not None else ''
    guest_names = set(re.findall(r'^.*\bT _?(\w+)\s*$', guest, re.M))
    for address, record in hooks.items():
        if record['provider'] not in names:
            raise ValueError(f'{record["record"]}: missing provider {record["provider"]}')
        if archive is not None and not {f'f_{address:08X}', original_name(address)} <= guest_names:
            raise ValueError(f'{record["record"]}: archive lacks wrapper/original; regenerate it')
