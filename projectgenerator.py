#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Jussi Pakkanen

import argparse, sys, os, pathlib, random

p = argparse.ArgumentParser(prog='Module test project generator')
p.add_argument('--source', help='Root dir for sources.', required=True)
p.add_argument('--build', help='Root dir for build.', required=True)

def gen_imports(template, i):
    imports = []
    if i < 1:
        return imports
    used_imports = set()
    num_imports = random.randrange(min(i, 4))
    while len(used_imports) < num_imports:
        modnum = random.randrange(i)
        if modnum not in used_imports:
            used_imports.add(modnum)
            imports.append(template % modnum)
    return imports

def create_sources(path, template, injected_imports=None):
    # injected_imports maps a source index to a list of module names to import
    # from *another* target -- this is how we wire up the cross-target case.
    injected_imports = injected_imports or {}
    srclist = []
    num_sources = 10
    for i in range(num_sources):
        fname = pathlib.Path(template % i).with_suffix('.cpp')
        modulename = template % i
        srclist.append(fname)
        full_name = path / fname
        with open(full_name, 'w') as ofile:
            ofile.write(f'export {modulename}\n\n')
            for imp in injected_imports.get(i, []):
                ofile.write(f'import {imp}\n')
            for imp in gen_imports(template, i):
                ofile.write(f'import {imp}\n')
    return srclist

def create_rules(ninjafile):
    tooldir = pathlib.Path(__file__).parent
    compiler = tooldir / 'compiler.py'
    linker = tooldir / 'linker.py'
    scanner = tooldir / 'scanner.py'
    collator = tooldir / 'collator.py'
    assert(compiler.is_file())
    assert(collator.is_file())

    ninjafile.write('rule compiler\n')
    ninjafile.write(f' command = {compiler} $args -o $out $in\n')
    ninjafile.write(' deps = gcc\n')
    ninjafile.write(' depfile = $DEPFILE\n')
    ninjafile.write(' description = Compiling source file $out\n')
    ninjafile.write('\n')

    ninjafile.write('rule linker\n')
    ninjafile.write(f' command = {linker} -o $out $in\n')
    ninjafile.write(' description = Linking target $out\n')
    ninjafile.write('\n')

    # One scan process per source, emitting P1689.
    ninjafile.write('rule scan\n')
    ninjafile.write(f' command = {scanner} -o $out $in\n')
    ninjafile.write(' description = Scanning $in\n')
    ninjafile.write('\n')

    # One collate process per target: P1689 (+ dependency provmaps) -> dyndep.
    ninjafile.write('rule collate\n')
    ninjafile.write(f' command = {collator} --dyndep $DD --provmap $PROVMAP $ARGS $in\n')
    ninjafile.write(' description = Collating dyndep $DD\n')
    ninjafile.write('\n')

    ninjafile.write('rule command\n')
    ninjafile.write(' command = $COMMAND\n')
    ninjafile.write(' description = $DESC\n')
    ninjafile.write('\n')


def emit_target(ninjafile, target_name, build_to_src, srclist,
                imported_provmaps, link_output, extra_link_inputs):
    target_dd = target_name + '.dd'
    target_pm = target_name + '.provmap'
    objfiles = []
    ddifiles = []

    for src in srclist:
        stem = pathlib.Path(src.name).stem
        objfile = stem + '.o'
        ddifile = stem + '.ddi'
        depfile = objfile + '.d'
        rel_src = build_to_src / src
        objfiles.append(objfile)
        ddifiles.append(ddifile)

        # Scan edge: one P1689 file per source, needs no module files to exist.
        ninjafile.write(f'build {ddifile}: scan {rel_src}\n\n')

        # Compile edge: static command line, ordering supplied by the dyndep.
        ninjafile.write(f'build {objfile}: compiler {rel_src} || {target_dd}\n')
        ninjafile.write(' args = \n')
        ninjafile.write(f' DEPFILE = {depfile}\n')
        ninjafile.write(f' dyndep = {target_dd}\n')
        ninjafile.write('\n')

    # Collate edge: consumes this target's .ddi files (explicit inputs) and the
    # dependency targets' provmaps (implicit inputs, so they exist first).
    ninjafile.write(f'build {target_dd} {target_pm}: collate ' +
                    ' '.join(ddifiles))
    if imported_provmaps:
        ninjafile.write(' | ' + ' '.join(imported_provmaps))
    ninjafile.write('\n')
    ninjafile.write(f' DD = {target_dd}\n')
    ninjafile.write(f' PROVMAP = {target_pm}\n')
    args = ' '.join(f'--imported-provmap {ip}' for ip in imported_provmaps)
    ninjafile.write(f' ARGS = {args}\n')
    ninjafile.write('\n')

    # Link edge: depends on the dependency libraries only -- no module info.
    link_inputs = list(objfiles) + list(extra_link_inputs)
    ninjafile.write(f'build {link_output}: linker ' + ' '.join(link_inputs))
    ninjafile.write('\n\n')

    return target_pm, link_output

def generate():
    args = p.parse_args()
    if os.path.exists(args.source):
        sys.exit('Source dir already exists.')
    if os.path.exists(args.build):
        sys.exit('Build dir already exists.')
    srcdir = pathlib.Path(args.source)
    builddir = pathlib.Path(args.build)
    build_to_src = pathlib.Path('..') / srcdir  # FIXME
    ninjafile = builddir / 'build.ninja'
    srcdir.mkdir()
    builddir.mkdir()
    with open(ninjafile, "w") as n:
        n.write('ninja_required_version = 1.11.2\n\n')
        n.write('# Rules\n\n')
        create_rules(n)
        n.write('# Target: modlib (a module-providing library)\n\n')
        modlib_src = create_sources(srcdir, 'modlib%d')
        modlib_pm, modlib_lib = emit_target(
            n, 'modlib', build_to_src, modlib_src,
            imported_provmaps=[], link_output='libmodlib.a',
            extra_link_inputs=[])

        # Target: app. It imports modules from modlib and links the library.
        # Nothing about modlib's sources is named here -- only its provmap and
        # the library file. app0 imports modlib0; app5 imports modlib1.
        n.write('# Target: app (imports modlib modules, links libmodlib.a)\n\n')
        app_src = create_sources(srcdir, 'app%d',
                                 injected_imports={0: ['modlib0'],
                                                   5: ['modlib1']})
        emit_target(
            n, 'app', build_to_src, app_src,
            imported_provmaps=[modlib_pm], link_output='prog',
            extra_link_inputs=[modlib_lib])

        n.write('# Housekeeping targets\n\n')
        n.write('build clean: phony actualclean\n\n')
        n.write('build actualclean: command\n')
        n.write(' COMMAND = ninja -t clean\n')
        n.write(' description = Cleaning\n\n')
        n.write('# The all important all target\n\n')
        n.write('build all: phony prog\n\n')
        n.write('default all\n')

if __name__ == '__main__':
    generate()
