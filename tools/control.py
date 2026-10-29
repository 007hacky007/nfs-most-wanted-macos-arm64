#!/usr/bin/env python3
"""Send a key or frame-capture request to this port's local test command file."""
import argparse
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('key',help='RETURN, LEFT, RIGHT, UP, DOWN, A-Z, ESCAPE, DUMP, or QUIT')
parser.add_argument('action',nargs='?',default='press',choices=('press','down','up'))
parser.add_argument('--file',type=Path,default=Path('out/commands.txt'))
args=parser.parse_args()
with args.file.open('a') as output:
    output.write(f'{args.key}\n' if args.key in ('DUMP','QUIT') else f'{args.key} {args.action}\n')
