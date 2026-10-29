import hashlib
import importlib
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch


HELPERS=((0x01c2dac7,0x01c2db47,0x01c2dadb,0x01c2dade),
         (0x01c2dbf1,0x01c2dc6c,0x01c2dc10,0x01c2dc2c),
         (0x01c2dc6c,0x01c2dd66,0x01c2dcda,0x01c2dceb))


def source_fixture():
    sources={}
    for index,(entry,_,store,load) in enumerate(HELPERS):
        middle=('assert(c->fcw==(expected_control|0x3fu));' if index==0 else
                'MR32(c->ebp-0x20u)=next_control;' if index==1 else
                'MR32(c->ebp-0x1cu)=next_status;')
        sources[f'shard_{index:04d}.c']=(f'void sub_{entry:08x}(CPU *restrict c) {{\n'
            f'    /* {store:08x}  fnstenv [ebp - 0x20] */\n'
            f'    unsupported_insn(c, 0x{store:x}u, "fnstenv");\n'
            f'    {middle}\n'
            f'    /* {load:08x}  fldenv [ebp - 0x20] */\n'
            f'    unsupported_insn(c, 0x{load:x}u, "fldenv");\n}}\n')
    return sources


def image_fixture():
    # Synthetic x86 DLL with three private frames at the pinned RVAs. It is
    # generated test data, not a copy of an original helper implementation.
    raw=bytearray(0x1200);raw[:2]=b'MZ';struct.pack_into('<I',raw,0x3c,0x80)
    raw[0x80:0x84]=b'PE\0\0';struct.pack_into('<HHIIIHH',raw,0x84,0x14c,1,0,0,0,0xe0,0x2102)
    opt=0x98;struct.pack_into('<H',raw,opt,0x10b)
    for offset,value in ((16,0x2dac7),(20,0x2d000),(28,0x10000000),(32,0x1000),
                         (36,0x200),(56,0x48000),(60,0x200),(92,16)):
        struct.pack_into('<I',raw,opt+offset,value)
    section=opt+0xe0;raw[section:section+5]=b'.text'
    struct.pack_into('<IIII',raw,section+8,0x1000,0x2d000,0x1000,0x200)
    struct.pack_into('<I',raw,section+36,0x60000020)
    raw[0x200:]=b'\x90'*0x1000
    def write(address,data):
        offset=address-0x01c2d000+0x200;raw[offset:offset+len(data)]=data
    for entry,end,store,load in HELPERS:
        write(entry,bytes.fromhex('8bff558bec83ec20'))
        write(store-12,bytes.fromhex('6a075933c08d7de0f3ab9090'))
        write(store,bytes.fromhex('d975e0'));write(load,bytes.fromhex('d965e0'))
        write(end-2,bytes.fromhex('c9c3'))
    return bytes(raw)


class HQCRTEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('tools/hq_crt_environment.py').is_file(),'tracked adapter missing')
        self.adapter=importlib.import_module('tools.hq_crt_environment')

    def test_exact_six_replacements_leave_other_source_and_traps_unchanged(self):
        sources=source_fixture();sources['other.c']='void sub_01c10000(CPU *c) {\n unsupported_insn(c, 0x1c10003u, "fnstenv");\n}\n'
        before=dict(sources);adapted=self.adapter.adapt_extraoptions_environment(sources)
        self.assertEqual(sources,before);self.assertEqual(adapted['other.c'],sources['other.c'])
        for name in sources:
            if name=='other.c':continue
            self.assertNotIn('unsupported_insn',adapted[name])
            self.assertEqual(adapted[name].count('c->fcw|=0x3fu;'),1)
            self.assertEqual(adapted[name].count('c->top=(c->fsw>>11)&7u;'),1)
        self.assertEqual(set(adapted),set(sources))

    def test_partial_duplicate_wrong_function_and_wrong_operand_fail_atomically(self):
        good=source_fixture()
        cases=[]
        missing=dict(good);missing.pop('shard_0000.c');cases.append(missing)
        duplicate=dict(good);duplicate['duplicate.c']=good['shard_0000.c'];cases.append(duplicate)
        for original,replacement in (('sub_01c2dac7','sub_01c20000'),('[ebp - 0x20]','[ebp - 0x1c]'),('"fnstenv"','"fldenv"')):
            wrong=dict(good);wrong['shard_0000.c']=wrong['shard_0000.c'].replace(original,replacement,1);cases.append(wrong)
        for sources in cases:
            before=dict(sources)
            with self.subTest(source=sources),self.assertRaises(ValueError):
                self.adapter.adapt_extraoptions_environment(sources)
            self.assertEqual(sources,before)

    def test_input_pin_operand_private_frame_and_unrepresented_fields_are_checked(self):
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            self.adapter.validate_extraoptions_environment(b'not the pinned module')
        raw=image_fixture()
        with patch.object(self.adapter,'EXTRAOPTIONS_SHA256',hashlib.sha256(raw).hexdigest()):
            self.adapter.validate_extraoptions_environment(raw)
            with self.assertRaisesRegex(ValueError,'base'):
                self.adapter.validate_extraoptions_environment(raw,guest_base=0x02400000)
        mutations=((0x01c2dadb+2,0xe4), # environment operand points at status
                   (0x01c2dac7+7,0x1c), # insufficient private frame
                   (0x01c2dadb-12+1,6), # zero initializer has only six dwords
                   (0x01c2dade+3,0x8b))
        for address,value in mutations:
            changed=bytearray(raw);offset=address-0x01c2d000+0x200;changed[offset]=value
            if address==0x01c2dade+3:changed[offset:offset+3]=bytes.fromhex('8b45e8')
            with patch.object(self.adapter,'EXTRAOPTIONS_SHA256',hashlib.sha256(changed).hexdigest()),self.subTest(address=hex(address)),self.assertRaises(ValueError):
                self.adapter.validate_extraoptions_environment(bytes(changed))

    def test_asset_free_native_control_status_top_and_frame_guards(self):
        adapted=self.adapter.adapt_extraoptions_environment(source_fixture())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'adapted.c').write_text(''.join(adapted.values()))
            binary=root/'check'
            build=subprocess.run(['clang','-O1','-Iruntime','-I'+str(root),'tests/hq_crt_environment.c','-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('represented environment roundtrips',run.stdout)


    def test_optional_actual_crt_control_and_exception_corpus(self):
        candidates=(Path('out/installed/.nfsmw/full/scripts/NFSMWExtraOptions.asi'),
                    Path('out/hq-extract/normalized/scripts/NFSMWExtraOptions.asi'))
        source=next((path for path in candidates if path.is_file()),None)
        if source is None:self.skipTest('requires pinned ExtraOptions module')
        raw=source.read_bytes();self.adapter.validate_extraoptions_environment(raw)
        import pefile
        from tools.lift import Lifter
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pe=pefile.PE(data=raw);pe.relocate_image(0x01c00000)
            pe.OPTIONAL_HEADER.ImageBase=0x01c00000;image=root/'image.dll';pe.write(str(image))
            (root/'memory.bin').write_bytes(pe.get_memory_mapped_image().ljust(0x48000,b'\0'))
            lifter=Lifter(str(image),trap=True,x87pc=True)
            pending=[0x01c2dac7,0x01c2dbf1,0x01c2dc6c,0x01c2db47];functions={}
            while pending:
                address=pending.pop()
                if address in functions:continue
                code,_=lifter.lift(address);functions[address]=code
                pending.extend(int(value,16)for value in re.findall(r'\bsub_([0-9a-f]{8})\(c\)',code)if int(value,16)not in functions)
            self.assertEqual(len(functions),8)
            adapted=self.adapter.adapt_extraoptions_environment({f'{address:x}.c':code for address,code in functions.items()})
            declarations=''.join(f'void sub_{address:08x}(CPU*);\n'for address in sorted(functions))
            (root/'adapted.c').write_text('void unsupported_insn(CPU*,uint32_t,const char*);\n'+declarations+''.join(adapted.values()))
            binary=root/'actual'
            build=subprocess.run(['clang','-O1','-DHQ_ACTUAL_CRT_ENVIRONMENT','-Iruntime','-I'+str(root),'tests/hq_crt_environment.c','-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary),str(root/'memory.bin')],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('1536 actual CRT control cases and 6 exception cases passed',run.stdout)


if __name__=='__main__':unittest.main()
