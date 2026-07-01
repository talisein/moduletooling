#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Jussi Pakkanen

# Collator. Consumes the P1689 scan results (.ddi) of every source in a target,
# plus the provided-module maps published by the target's dependencies, and
# produces:
#   * a Ninja dyndep file ordering this target's compilations, and
#   * this target's own provided-module map (name -> module file).
#
# All module-file paths are derived from the documented name->file scheme
# (module2filename), never by scanning output filenames. This is the whole
# jussi-path split: the scanner learns names, the collator turns names into
# ordering, and the compiler never sees a module name on its command line.

import argparse, sys, os, json
from compiler import module2filename

p = argparse.ArgumentParser(prog='Fake collator')
p.add_argument('--dyndep', required=True, help='Output Ninja dyndep file.')
p.add_argument('--provmap', required=True,
               help='Output provided-module map for this target.')
p.add_argument('--imported-provmap', action='append', default=[],
               help='Provided-module map of a dependency target. Repeatable.')
p.add_argument('ddis', nargs='+', help='This target\'s P1689 scan results.')

def load_rules(ddifiles):
    rules = []
    for f in ddifiles:
        with open(f) as ddi:
            data = json.load(ddi)
        for rule in data.get('rules', []):
            rules.append(rule)
    return rules

def collate():
    args = p.parse_args()
    rules = load_rules(args.ddis)

    # name -> module file, for everything this target can resolve.
    resolvable = {}
    # name -> module file, for what this target itself provides (the artifact
    # we publish for our consumers).
    provided = {}

    for rule in rules:
        for prov in rule.get('provides', []):
            name = prov['logical-name']
            if name in provided:
                sys.exit(f'Module {name} is provided by two sources in this '
                         f'target. Module names must be unique.')
            modfile = module2filename(name)
            provided[name] = modfile
            resolvable[name] = modfile

    for pmfile in args.imported_provmap:
        with open(pmfile) as pm:
            imported = json.load(pm)
        for name, modfile in imported.items():
            if name in resolvable:
                sys.exit(f'Module {name} is provided both locally and by a '
                         f'dependency ({pmfile}). Module names must be unique '
                         f'across the link.')
            resolvable[name] = modfile

    with open(args.dyndep, 'w') as dd:
        dd.write('ninja_dyndep_version = 1\n\n')
        for rule in rules:
            obj = rule['primary-output']
            outputs = [p['logical-name'] for p in rule.get('provides', [])]
            reqs = []
            for req in rule.get('requires', []):
                name = req['logical-name']
                modfile = resolvable.get(name)
                if modfile is None:
                    sys.exit(f'Source producing {obj} requires module {name}, '
                             f'which is provided by no target in this build.')
                reqs.append(modfile)
            dd.write(f'build {obj}')
            if outputs:
                dd.write(' | ' + ' '.join(module2filename(o) for o in outputs))
            dd.write(': dyndep')
            if reqs:
                dd.write(' | ' + ' '.join(reqs))
            dd.write('\n')

    with open(args.provmap, 'w') as pm:
        json.dump(provided, pm, indent=2)
        pm.write('\n')

if __name__ == '__main__':
    collate()
