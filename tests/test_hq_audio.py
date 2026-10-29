"""The audio repair accepts only verified module states and edits its patch."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGE_SHA = '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'


@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS runtime')
class AudioRepairTests(unittest.TestCase):
    def test_four_states_idempotence_and_every_byte_tamper(self):
        import pefile
        image = Path(os.environ.get('NFSMW_CANONICAL_IMAGE', ROOT / 'out/installed/.nfsmw/runtime.exe'))
        if not image.is_file():
            self.skipTest('requires optional canonical image')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), IMAGE_SHA)
        original = pefile.PE(str(image)).get_data(0x4c41d7 - 0x400000, 34)
        fixtures = bytearray()
        for repaired in (False, True):
            for rate in (22050, 44100):
                data = bytearray(original)
                struct.pack_into('<I', data, 18, 48000)
                if repaired:
                    data[22:24] = bytes((0xeb, 10))
                else:
                    data[22:27] = bytes((0xe9,)) + struct.pack('<i', 7)
                struct.pack_into('<I', data, 30, rate)
                fixtures.extend(data)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'fixtures.bin').write_bytes(fixtures)
            source = directory / 'test.c'
            source.write_text(r'''
#include "cpu.h"
#include "hq_audio.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *g_mem;uint8_t g_cbits[1u<<15];
int main(int argc,char**argv){
 assert(argc==2);g_mem=calloc(1,0xa00000);assert(g_mem);
 const uint32_t address=0x4c41d7,page=address>>14;
 g_cbits[page>>3]|=1u<<(page&7);
 uint8_t fixtures[4][34],before[66];FILE*f=fopen(argv[1],"rb");assert(f);
 assert(fread(fixtures,sizeof fixtures,1,f)==1);fclose(f);
 for(unsigned state=0;state<4;state++)for(unsigned high=0;high<2;high++){
  memset(g_mem+address-16,0xa5,sizeof before);memcpy(g_mem+address,fixtures[state],34);
  memcpy(before,g_mem+address-16,sizeof before);
  assert(hq_audio_repair(high));assert(!memcmp(g_mem+address,fixtures[2+high],34));
  assert(!memcmp(g_mem+address-16,before,16)&&!memcmp(g_mem+address+34,before+50,16));
  assert(!memcmp(g_mem+address,before+16,22)&&!memcmp(g_mem+address+27,before+43,3));
  assert(hq_audio_repair(high)&&!memcmp(g_mem+address,fixtures[2+high],34));
 }
 for(unsigned state=0;state<4;state++)for(unsigned byte=0;byte<34;byte++)for(unsigned bit=0;bit<8;bit++){
  memcpy(g_mem+address,fixtures[state],34);MR8(address+byte)^=1u<<bit;
  memcpy(before,g_mem+address,34);assert(!hq_audio_repair(1));
  assert(!memcmp(g_mem+address,before,34));
 }
 memcpy(g_mem+address,fixtures[0],34);g_cbits[page>>3]=0;
 assert(!hq_audio_repair(1)&&!memcmp(g_mem+address,fixtures[0],34));
 free(g_mem);return 0;
}
''')
            flags = ['-O1', '-I' + str(ROOT / 'runtime')]
            if os.environ.get('NFSMW_AUDIO_SANITIZE') == '1':
                flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            built = subprocess.run(['clang', *flags, str(source), str(ROOT / 'runtime/hq_audio.c'),
                                    '-o', str(directory / 'test')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(directory / 'test'), str(directory / 'fixtures.bin')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
