#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Jussi Pakkanen

# Per-source dependency scanner. Emits P1689r5 JSON describing what a single
# translation unit provides and requires. It does NOT know about module file
# names, search directories or build ordering -- that is the collator's job.
# Crucially the scan needs no module files to exist yet.

import argparse, sys, os, json
from compiler import parse_source

p = argparse.ArgumentParser(prog='Fake dep scanner (P1689r5)')
p.add_argument('-o', dest='ddifile', required=True, help='Output P1689 file.')
p.add_argument('source', help='The single source file to scan.')

def src2obj(cppfile):
    # The hackiest of hacks. <o>
    return os.path.split(cppfile)[1][:-4] + '.o'

def scan():
    args = p.parse_args()
    if not os.path.exists(args.source):
        sys.exit(f'Source file {args.source} does not exist.')
    presults = parse_source(args.source)
    rule = {'primary-output': src2obj(args.source)}
    if presults.export:
        rule['provides'] = [{'logical-name': presults.export,
                             'source-path': args.source,
                             'is-interface': True}]
    if presults.imports:
        rule['requires'] = [{'logical-name': imp} for imp in presults.imports]
    p1689 = {'version': 1,
             'revision': 0,
             'rules': [rule]}
    with open(args.ddifile, 'w') as ddifile:
        json.dump(p1689, ddifile, indent=2)
        ddifile.write('\n')

if __name__ == '__main__':
    scan()
