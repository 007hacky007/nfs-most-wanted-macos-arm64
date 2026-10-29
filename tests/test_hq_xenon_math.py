from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,'.')
import pefile
from tools.lift import RawLifter

ROOT=Path('tests')
ADAPTER=Path('runtime/hq_xenon_math.c')


class XenonMathTests(unittest.TestCase):
    def test_native_values_and_cpu_contract(self):
        self.assertTrue(ADAPTER.is_file(),'native math adapter is missing')
        self.compile_run('')

    @unittest.skipUnless(Path('out/installed/.nfsmw/full/scripts/NFSMW_XenonEffects.asi').is_file(),'requires the optional pinned local Xenon ASI')
    def test_actual_pinned_cdecl_caller(self):
        self.assertTrue(ADAPTER.is_file(),'native math adapter is missing')
        source=Path('out/installed/.nfsmw/full/scripts/NFSMW_XenonEffects.asi')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         '5dcad612125be0f13426644b044a2a18874fc2d84726c033e97975e262256692')
        pe=pefile.PE(str(source))
        matches=[(library.dll,entry.address-pe.OPTIONAL_HEADER.ImageBase) for library in pe.DIRECTORY_ENTRY_IMPORT
                 for entry in library.imports if entry.name==b'fminf']
        self.assertEqual(matches,[(b'api-ms-win-crt-math-l1-1-0.dll',0xd128)])
        pe.relocate_image(0x2400000)
        data=pe.get_data(0x94e0,0x34)
        lifter=RawLifter(data+b'\xc3',base=0x24094e0,x87pc=True)
        code,_=lifter.lift(0x24094e0)
        self.assertIn('PUSH32(0x2409501u)',code)
        self.assertIn('MR32(0x240d128u)',code)
        self.assertIn('FPOP()',code)
        self.assertEqual(pe.get_data(0xfe80,4).hex(),'00002842')
        self.compile_run(code)

    def compile_run(self,code):
        with tempfile.TemporaryDirectory() as tmp:
            fragment=Path(tmp)/'fragment.inc';fragment.write_text(code)
            binary=Path(tmp)/'check'
            command=['clang','-O1','-Iruntime','-I'+str(ROOT),'-I'+tmp,
                     '-DACTUAL_CALLER='+str(int(bool(code))),
                     str(ROOT/'hq_xenon_math.c'),str(ADAPTER),'-lm','-o',str(binary)]
            build=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
