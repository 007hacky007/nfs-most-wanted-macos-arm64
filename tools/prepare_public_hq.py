"""Derive the Full HQ native build from supplied files without private captures."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def mapped_image(image):
    size=image.OPTIONAL_HEADER.SizeOfImage
    data=image.get_memory_mapped_image()[:size]
    return data+bytes(size-len(data))


def checkpoint_ranges():
    schema=json.loads((ROOT/'tools/hq_checkpoints.json').read_text())
    return [(field['address'],field.get('size',4)) for point in schema['points']
            if point['name']=='eohotkeys' for field in point['fields']]


def capture_images(directory,size):
    directory=Path(directory)
    if directory.is_symlink() or any(path.is_symlink() for path in directory.rglob('*')):
        raise ValueError('native preparation capture contains a symlink')
    images=[]
    for meta in sorted(directory.glob('*.json')):
        record=json.loads(meta.read_text())
        if (not record.get('complete') or record.get('game_base')!=0x400000 or
                record.get('game_size')!=size):
            raise ValueError('incomplete native preparation capture: '+meta.name)
        if not re.fullmatch(r'[0-9]{4}-[a-z]+',meta.stem):
            raise ValueError('unexpected native preparation capture: '+meta.name)
        reason=record.get('reason')
        if reason!=meta.stem.split('-',1)[1]:
            raise ValueError('native preparation reason differs')
        image=meta.with_suffix('.game.bin')
        if not image.is_file() or image.stat().st_size!=size:
            raise ValueError('native preparation image size differs')
        images.append((reason,image))
    if not images:
        raise ValueError('native preparation produced no captures')
    return images


def run(command,log,*,environment=None,timeout=None,accepted=(0,)):
    print('Preparing '+log.stem.replace('-',' '),flush=True)
    with log.open('w') as stream:
        try:
            result=subprocess.run(list(map(str,command)),cwd=ROOT,env=environment,
                                  stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise ValueError('native preparation timed out; inspect '+str(log)) from error
    if result.returncode not in accepted:
        raise ValueError(f'preparation failed ({result.returncode}); inspect {log}')
    return result.returncode


def prepare_build(game,output):
    """Generate, bootstrap finite patch states, and link the native application."""
    for name in ('RELOCS','SEEDS','GENOUT','SYMPFX','IMPOUT','IMPDLL','STRICT','COMMENTS',
                 'WATCH','COVERAGE','LREGS','X87OPT','FTOL2INL','NOCLOSURE','JTSWITCH',
                 'INLINE','INLINE_LIST','INLINE_MAX','OVERRIDE','HOOKS','BRANCH_HOOKS',
                 'FLAGABI','CODE_RVA_START'):
        os.environ.pop(name,None)
    os.environ.update(X87PC='1',RETEIP='1',FLAGOPT='1')
    try:
        from .prepare_audio_callbacks import prepare as prepare_audio
        from .prepare_hq_modules import prepare_modules
        from .prepare_hq_runtime import prepare_runtime
        from .prepare_hq_routes import generate
        from .prepare_hq_phases import prepare_phases
        from .hq_module_catalog import MODULES
        from .runtime_image import STANDARD_RUNTIME_SHA256
        from . import progress
    except ImportError:
        from prepare_audio_callbacks import prepare as prepare_audio
        from prepare_hq_modules import prepare_modules
        from prepare_hq_runtime import prepare_runtime
        from prepare_hq_routes import generate
        from prepare_hq_phases import prepare_phases
        from hq_module_catalog import MODULES
        from runtime_image import STANDARD_RUNTIME_SHA256
        import progress
    import pefile

    game,output=Path(game).resolve(),Path(output).resolve()
    if output.exists():
        raise ValueError('public preparation requires a fresh output directory')
    output.mkdir(parents=True)
    python=Path(sys.executable)
    progress.step('translate','Translating the game to C')
    run(['sh',ROOT/'gen.sh',game],output/'generate.log')
    canonical=game/'.nfsmw/runtime.exe'
    if sha(canonical)!=STANDARD_RUNTIME_SHA256:
        raise ValueError('unsupported canonical game executable')
    image=pefile.PE(str(canonical));size=image.OPTIONAL_HEADER.SizeOfImage
    mapped=mapped_image(image)
    baseline=output/'canonical.game.bin';baseline.write_bytes(mapped)
    audio=output/'audio'
    progress.step('audio','Preparing native audio callbacks from verified game banks')
    prepare_audio(game,canonical,audio)
    progress.step('modules','Generating the six original runtime modules')
    modules=prepare_modules(game,ROOT/'out/hq-modules',ROOT/'gen/hq')
    prepare_runtime(ROOT/'gen/hq',ROOT/'gen/hq-runtime')
    routes=output/'routes'
    snapshots=[]
    text=next(section for section in image.sections if section.Name.rstrip(b'\0')==b'.text')
    text_slice=slice(text.VirtualAddress,text.VirtualAddress+text.Misc_VirtualSize)
    seen={hashlib.sha256(mapped[text_slice]).hexdigest()}
    capture_records=[]
    wrappers={f'sub_{entry:08x}_body':entry for module in MODULES for entry in module.wrappers}
    declarations=[ROOT/'gen/hq'/module.key/'decls.h' for module in MODULES]
    environment=os.environ.copy()
    for name in list(environment):
        if (name.startswith(('NFSMW_','NFSU2_')) or name in
                ('WINDOW','GPUVS','DUMPFRAME','DUMPDIR','DUMPCHUNKS','DUMPTEX','DRAWLIST','PERFLOG',
                 'SNDDUMP','RTIDLOG','GPUVSLOG','NOFOCUS','NFSRES','ALARM','ENHANCED')):
            environment.pop(name,None)
    environment.update(NFSMW_MODE='full',NFSMW_EXPERIMENTAL_FULL='1',ALARM='240')
    captures=[]

    def add(images):
        added=0
        for reason,path in images:
            data=path.read_bytes()
            if data[:image.OPTIONAL_HEADER.SizeOfHeaders]!=mapped[:image.OPTIONAL_HEADER.SizeOfHeaders]:
                raise ValueError('captured game headers differ from the supported executable')
            digest=hashlib.sha256(data[text_slice]).hexdigest()
            capture_records.append({'reason':reason,'sha256':sha(path),'text_sha256':digest})
            if digest not in seen:
                seen.add(digest);snapshots.append((f'phase{len(snapshots)}',path));added+=1
        return added

    def compile_routes(label):
        print(f'Generating guarded native routes for {len(snapshots)+1} code states',flush=True)
        record=generate(canonical,ROOT/'gen/all',snapshots,routes,modules['game_entrypoints'],
                        ROOT/'out/widescreen-hooks.txt',ROOT/'out/native-branches.txt',declarations,
                        wrappers,patch_ranges=checkpoint_ranges())
        run([python,ROOT/'tools/build_native.py','--hq','--hq-routes',routes,
             '--audio-callbacks',audio],output/(label+'-build.log'))
        return record

    def capture(label,option):
        folder=output/label;folder.mkdir()
        profile=output/(label+'-profile');profile.mkdir()
        env=dict(environment,NFSMW_HQ_CAPTURE_DIR=str(folder),NFSMW_SAVEDIR=str(profile))
        status=run([ROOT/'out/nfsmw_boot',option,game/'.nfsmw/full/speed.exe'],
                   output/(label+'.log'),environment=env,timeout=250,accepted=(0,78))
        images=capture_images(folder,size)
        captures.append({'stage':label,'status':status,'engine_sha256':sha(ROOT/'out/nfsmw_boot')})
        return status,images

    progress.step('bootstrap','First native build and module start-up')
    compile_routes('bootstrap')
    status,images=capture('module-init','--prepare-hq-modules')
    if status:
        raise ValueError('original module initialization failed before game preparation')
    add(images)
    for attempt in range(12):
        progress.step('runtime',f'Finding the remaining code states, round {attempt+1} of at most 12')
        compile_routes(f'runtime-{attempt}')
        status,images=capture(f'runtime-{attempt}','--prepare-hq-runtime')
        added=add(images)
        if status==0:
            reasons={reason for reason,_ in images}
            if not {'boot','xenoninit','cartypes','eohotkeys','modules'}<=reasons:
                raise ValueError('native preparation did not reach every required writer')
            if sum(reason=='eohotkeys' for reason,_ in images)!=8:
                raise ValueError('native preparation did not enumerate eight hotkey states')
            if not added:
                break
            continue
        if not added:
            raise ValueError('native preparation repeated an unknown code state without progress')
    else:
        raise ValueError('native preparation exceeded the finite code-state limit')
    upstream=next(path for reason,path in reversed(images) if reason=='xenoninit')
    render=prepare_phases(game,upstream,output/'renderer',baseline_sha256=sha(upstream))
    add([('callback',render[0]),('render',render[1])])
    progress.step('final','Final native build and verification run')
    record=compile_routes('final')
    status,images=capture('verify','--prepare-hq-runtime')
    if status or add(images):
        raise ValueError('final native preparation has an uncompiled code state')
    manifest={'version':1,'producer':'public-native-build','canonical_sha256':sha(canonical),
              'engine_sha256':sha(ROOT/'out/nfsmw_boot'),'captures':captures,
              'snapshots':capture_records,'route_functions':len(record['functions']),
              'continuations':len(record['extra_entries']),'traps':record['traps']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest
