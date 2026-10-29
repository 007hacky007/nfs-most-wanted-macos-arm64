"""Accept runtime operands only when their values occur in generated game phases."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import pefile

BASE=0x400000
CANONICAL='80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'
SCHEMA=json.loads(Path(__file__).with_name('hq_checkpoints.json').read_text())
FIELDS=tuple(tuple(field['address']for field in point['fields'])for point in SCHEMA['points'])


def prepare(routes,output):
    record=json.loads((routes/'manifest.json').read_text())
    baseline=routes/'image0.exe'
    if hashlib.sha256(baseline.read_bytes()).hexdigest()!=CANONICAL:
        raise ValueError('checkpoint baseline is not the supported canonical image')
    widths=tuple(tuple(field.get('size',4)for field in point['fields'])for point in SCHEMA['points'])
    if any(size not in (1,4)for sizes in widths for size in sizes):raise ValueError('unsupported checkpoint field size')
    values=[set()for _ in FIELDS];original=None
    consumers={row['entry']:row for row in record['functions']}
    for index in range(len(record['phases'])):
        pe=pefile.PE(str(routes/f'image{index}.exe'))
        if pe.OPTIONAL_HEADER.ImageBase!=BASE:raise ValueError('unexpected game base')
        image=pe.get_memory_mapped_image()
        row=[tuple(int.from_bytes(image[a-BASE:a-BASE+size],'little')for a,size in zip(fields,sizes))for fields,sizes in zip(FIELDS,widths)]
        if original is None:original=row
        for point,fields in enumerate(FIELDS):
            for field,before,after in zip(SCHEMA['points'][point]['fields'],original[point],row[point]):
                address=field['address'];size=field.get('size',4);consumer=consumers.get(field['consumer'],{})
                covered=any(start<=address and address+size<=start+length for start,length in consumer.get('ranges',[]))
                if before!=after and not covered:
                    raise ValueError('runtime operand missing from route coverage')
            values[point].add(row[point])
    code=['#include "cpu.h"','int hq_checkpoint_known(unsigned point){']
    for point,fields in enumerate(FIELDS,1):
        alternatives=['('+'&&'.join(f'MR{size*8}(0x{address:08x}u)==0x{value:08x}u'for address,size,value in zip(fields,widths[point-1],row))+')'for row in sorted(values[point-1])]
        code.append(f'    if(point=={point})return '+ '||'.join(alternatives)+';')
    code+=['    return 0;','}']
    with tempfile.NamedTemporaryFile('w',dir=output.parent,delete=False)as stream:
        temporary=Path(stream.name)
        try:stream.write('\n'.join(code)+'\n');stream.flush();temporary.replace(output)
        finally:temporary.unlink(missing_ok=True)
    metadata={'game_sha256':CANONICAL,'points':[]}
    for point,rows in zip(SCHEMA['points'],values):
        item=dict(point);item['accepted_tuples']=[list(row)for row in sorted(rows)]
        item['consumer_signatures']=[consumers[field['consumer']]for field in point['fields']if field['consumer']in consumers]
        metadata['points'].append(item)
    output.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print('Prepared checkpoint tuples:',*[len(rows)for rows in values])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routes',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();prepare(args.routes,args.output)
