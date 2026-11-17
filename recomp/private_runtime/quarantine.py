"""Compiler-expanded audit for selected host runtime sources.

Unsafe implementations are rejected. Neither host nor guest source is rewritten.
"""
import subprocess


def checked_engine_initializers(objects):
    """No engine object may install a native process-start initializer."""
    if not objects:return
    result=subprocess.run(['otool','-l',*map(str,objects)],capture_output=True,text=True,check=True)
    count=result.stdout.count('sectname __mod_init_func')
    if count:raise ValueError(f'private engine objects retain {count} initializer sections')


def children(node):
    yield node
    for item in node.get('inner', []):
        yield from children(item)


def audit_tree(tree, ranges):
    """Inspect compiler-expanded bodies AND initializers without changing them.

    Results retain declaration identities for aliases/callbacks and function names
    for cross-TU closure. Address-shaped arithmetic alone is not a guest access.
    """
    def refs(node):
        return {n.get('referencedDecl', {}).get('id') for n in children(node)
                if n.get('kind') == 'DeclRefExpr'}

    def callee(node):
        return next((n.get('referencedDecl', {}).get('name', '')
                     for n in children(node.get('inner', [{}])[0])
                     if n.get('kind') == 'DeclRefExpr'), '')

    def literal_values(node):
        return {int(n['value']) for n in children(node)
                if n.get('kind') == 'IntegerLiteral'
                and any(lo <= int(n['value']) < hi for lo, hi in ranges)}

    nodes = list(children(tree))
    variables = {n['id']: n for n in nodes
                 if n.get('kind') in ('VarDecl', 'EnumConstantDecl')}
    addresses = {key: literal_values(n) for key, n in variables.items()}
    def values(node):
        return literal_values(node) | set().union(*(addresses.get(r, set()) for r in refs(node)))

    def direct_base(node):
        return any((n.get('kind') == 'DeclRefExpr' and
                    n.get('referencedDecl', {}).get('name') == 'G') or
                   (n.get('kind') == 'CallExpr' and callee(n) == 'guest_base')
                   for n in children(node))

    aliases = {key for key, n in variables.items() if direct_base(n)}
    while True:
        changed = False
        for key, n in variables.items():
            new = values(n) - addresses[key]
            if new:
                addresses[key].update(new); changed = True
            if key not in aliases and refs(n) & aliases:
                aliases.add(key); changed = True
        if not changed:
            break

    def guest_pointer(node):
        return direct_base(node) or bool(refs(node) & aliases)

    def accesses(node, write=False):
        kind = node.get('kind'); parts = node.get('inner', [])
        if kind in ('BinaryOperator', 'CompoundAssignOperator') and node.get('opcode') in ('=', '+=', '-=', '|=', '&=', '^='):
            yield from accesses(parts[0], True)
            for n in parts[1:]: yield from accesses(n)
            return
        if kind == 'UnaryOperator' and node.get('opcode') in ('++', '--'):
            yield from accesses(parts[0], True)
            return
        pointer = kind == 'ArraySubscriptExpr' or (kind == 'UnaryOperator' and node.get('opcode') == '*')
        # G+constant passed to memcpy/memset is also a guest memory access.
        absolute = any(n.get('castKind') == 'IntegralToPointer' for n in children(node))
        if pointer and (guest_pointer(node) or absolute):
            for address in values(node): yield ('write' if write else 'read', address)
            return
        if kind == 'CallExpr':
            name = callee(node)
            if name in ('memcpy', 'memmove', 'memset', 'strncpy', 'strncmp', 'fwrite'):
                for i, arg in enumerate(parts[1:]):
                    if guest_pointer(arg):
                        for address in values(arg):
                            yield ('write' if i == 0 and name in ('memcpy', 'memmove', 'memset', 'strncpy') else 'read', address)
            if name in ('call', 'host_call', 'guest_call'):
                for arg in parts[1:]:
                    for address in values(arg): yield ('call', address)
        for n in parts:
            yield from accesses(n, write)

    rows = []
    current_file = ''
    for decl in tree.get('inner', []):
        loc = decl.get('loc', {})
        loc = loc.get('expansionLoc', loc)
        current_file = loc.get('presumedFile', loc.get('file', current_file))
        kind = decl.get('kind')
        body = next((n for n in decl.get('inner', []) if n.get('kind') == 'CompoundStmt'), None)
        if kind not in ('FunctionDecl', 'VarDecl') or (kind == 'FunctionDecl' and body is None):
            continue
        node = body if body is not None else decl
        rows.append({'name': decl.get('name', ''), 'source': current_file,
                     'kind': 'function' if body is not None else 'initializer',
                     'static': decl.get('storageClass') == 'static',
                     'constructor': any(n.get('kind') == 'ConstructorAttr' for n in decl.get('inner', [])),
                     'accesses': sorted(set(accesses(node))),
                     'calls': sorted({callee(n) for n in children(node) if n.get('kind') == 'CallExpr'}),
                     'references': sorted({n.get('referencedDecl', {}).get('name', '') for n in children(node)
                                           if n.get('kind') == 'DeclRefExpr'})})
    return rows


def quarantine(path, flags, ranges, *, restore=(), portable=None):
    """Audit selected source without ever modifying it; unsafe bodies fail closed."""
    from layers import audit_unit, check_audits, load_manifest
    if restore:
        raise ValueError('audit-only quarantine cannot restore or rewrite bodies')
    manifest = load_manifest()
    audit = audit_unit(path, flags, ranges)
    if portable is False:
        raise ValueError('engine implementation selected for audit-only runtime')
    check_audits([audit], manifest, manifest['targets']['private']['extra_sources'])
    return []
