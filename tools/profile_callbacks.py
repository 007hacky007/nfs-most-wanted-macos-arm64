#!/usr/bin/env python3
"""Collect native callback templates from bounded, offline bring-up runs."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--script',type=Path)
parser.add_argument('--runs',type=int,default=8,choices=range(1,33))
parser.add_argument('--seconds',type=int,default=60,choices=range(1,601))
args=parser.parse_args()
environment=os.environ.copy()
environment.pop('WINDOW',None)
environment['ALARM']=str(args.seconds)
if args.script:environment['NFSMW_INPUT_SCRIPT']=str(args.script)
Path('out/traces').mkdir(parents=True,exist_ok=True)
for attempt in range(args.runs):
    with open('out/traces/profile-build.log','w') as log:
        subprocess.run(['./build.sh'],stdout=log,stderr=subprocess.STDOUT,check=True)
    for name in ('out/missing-code.bin','out/missing-code-address.txt'):
        Path(name).unlink(missing_ok=True)
    path=Path(f'out/traces/profile-{attempt:02d}.log')
    with path.open('w') as log:
        try:
            result=subprocess.run(['out/nfsmw_boot','game/speed.exe'],env=environment,
                                  stdout=log,stderr=subprocess.STDOUT,timeout=args.seconds+10)
        except subprocess.TimeoutExpired:
            sys.exit(f'Bring-up exceeded the external timeout; inspect {path}')
    if result.returncode in (0,124):
        print(f'Bring-up ended with status {result.returncode}; inspect {path}. Menu/race acceptance is separate.')
        break
    if result.returncode!=80 or not Path('out/missing-code.bin').exists():
        sys.exit(f'Bring-up stopped with status {result.returncode}; inspect {path}')
    subprocess.run([sys.executable,'tools/lift_callbacks.py','--capture','--arena'],check=True)
else:
    sys.exit('Callback capture limit reached; inspect out/traces before continuing')
