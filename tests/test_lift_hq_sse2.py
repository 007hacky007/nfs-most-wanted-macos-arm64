import unittest
from tools.lift import RawLifter
from tests import test_lift_rain


class HQSSE2Tests(unittest.TestCase):
    compile = test_lift_rain.RainDecodeTests.compile

    def test_pshuflw_register_alias_and_memory(self):
        code, _ = RawLifter(bytes.fromhex('f20f70c11bf20f70c900f20f7010ffc3')).lift(0x401000)
        self.compile(code, r'''
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=0x9000;c->cf=c->zf=1;
uint16_t words[8]={0,0xffff,0x8000,0x7fff,0x1234,0xabcd,0xfe01,0x9876};
uint16_t memory[8]={0xffff,0x8001,0x8765,0xfedc,4,0xaaaa,0x5555,0xff00};
memcpy(&c->xmm[1],words,16);memcpy(g_mem+0x9000,memory,16);PUSH32(0xdeadbeef);sub_00401000(c);
uint16_t actual[3][8];memcpy(actual,c->xmm,sizeof actual);
for(unsigned i=0;i<8;i++){
 assert(actual[0][i]==(i<4?words[3-i]:words[i]));
 assert(actual[1][i]==(i<4?words[0]:words[i]));
 assert(actual[2][i]==(i<4?memory[3]:memory[i]));
}assert(c->cf&&c->zf&&c->esp==0x8000&&c->eip==0xdeadbeef);
''')

    def test_unpckhpd_preserves_bits_with_alias_and_memory(self):
        code, _ = RawLifter(bytes.fromhex('660f15c1660f15c9660f1510c3')).lift(0x401000)
        self.compile(code, r'''
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=0x9000;c->cf=c->zf=1;
c->xmm[0].u64[1]=0x7ff8000012345678ull;c->xmm[1].u64[1]=0x8000000000000000ull;
c->xmm[2].u64[1]=0xfff0000000000000ull;MR64(0x9008)=0x7ff80000abcdef01ull;
PUSH32(0xdeadbeef);sub_00401000(c);
assert(c->xmm[0].u64[0]==0x7ff8000012345678ull&&c->xmm[0].u64[1]==0x8000000000000000ull);
assert(c->xmm[1].u64[0]==0x8000000000000000ull&&c->xmm[1].u64[1]==0x8000000000000000ull);
assert(c->xmm[2].u64[0]==0xfff0000000000000ull&&c->xmm[2].u64[1]==0x7ff80000abcdef01ull);
assert(c->cf&&c->zf&&c->esp==0x8000&&c->eip==0xdeadbeef);
''')


if __name__ == '__main__':
    unittest.main()
