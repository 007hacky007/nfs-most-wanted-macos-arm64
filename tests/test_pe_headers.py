from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'), 'requires the native macOS memory loader')
class PEHeaderTests(unittest.TestCase):
    def test_original_headers_are_mapped_and_oversized_headers_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = bytearray(1024)
            image[:2] = b'MZ'
            struct.pack_into('<I', image, 0x3c, 0x80)
            image[0x80:0x84] = b'PE\0\0'
            struct.pack_into('<HH', image, 0x84, 0x14c, 1)
            struct.pack_into('<H', image, 0x94, 224)
            optional = 0x98
            struct.pack_into('<H', image, optional, 0x10b)
            for offset, value in ((16, 0x1000), (28, 0x400000), (32, 0x1000),
                                  (36, 0x200), (56, 0x2000), (60, 0x200), (92, 16)):
                struct.pack_into('<I', image, optional + offset, value)
            section = optional + 224
            image[section:section + 8] = b'.text\0\0\0'
            struct.pack_into('<IIII', image, section + 8, 16, 0x1000, 512, 512)
            image[512:528] = b'section payload!'
            valid = root/'valid.exe'
            valid.write_bytes(image)
            source = root/'headers.c'
            source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdio.h>
int mem_load_pe(const char*);
int main(int argc,char**argv){assert(argc>=2);int result=mem_load_pe(argv[1]);
if(argc>2){assert(result!=0);return 0;}assert(!result);
FILE*f=fopen(argv[1],"rb");assert(f);unsigned char expected[512];assert(fread(expected,1,512,f)==512);fclose(f);
assert(!memcmp(g_mem+0x400000,expected,512));assert(MR16(0x400000)==0x5a4d);
assert(MR32(0x400000+MR32(0x40003c)+0x28)==0x1000);
assert(!memcmp(g_mem+0x401000,"section payload!",16));}
''')
            binary = root/'headers'
            subprocess.run(['clang', '-O1', '-Wl,-dead_strip', '-Iruntime', str(source),
                            'runtime/mem.c', '-o', str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary), str(valid)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, header_size, file_size in (('past_file', 0x800, 1024), ('past_image', 0x3000, 0x4000)):
                with self.subTest(name=name):
                    malformed = image + bytes(file_size-len(image))
                    struct.pack_into('<I', malformed, optional + 60, header_size)
                    path = root/(name+'.exe')
                    path.write_bytes(malformed)
                    result = subprocess.run([str(binary), str(path), 'invalid'], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
