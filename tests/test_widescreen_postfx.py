"""Native WS postfx proof against the supplied September 2026 ASI."""
from pathlib import Path
import hashlib,struct,subprocess,tempfile,unittest,zipfile
import pefile
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT
class PostFXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.directory=Path(cls.temp.name)
        cls.com=cls.directory/'com';cls.gpu=cls.directory/'gpu';cls.translate=cls.directory/'translate'
        common=['-I'+str(NATIVE/'runtime'),'-I'+str(ROOT/'runtime'),str(ROOT/'runtime/vsemu.c'),'-Wl,-undefined,dynamic_lookup']
        subprocess.run(['clang',str(NATIVE/'tests/backend_widescreen_postfx_com.c'),*common,'-o',str(cls.com)],check=True,capture_output=True)
        subprocess.run(['clang','-fobjc-arc',str(NATIVE/'tests/backend_widescreen_postfx_gpu.m'),*common,'-framework','Foundation','-framework','Metal','-framework','AppKit','-framework','QuartzCore','-framework','GameController','-framework','IOKit','-o',str(cls.gpu)],check=True,capture_output=True)
        subprocess.run(['clang','-I'+str(ROOT/'runtime'),str(ROOT/'tests/shader_sm3.c'),str(ROOT/'runtime/vsemu.c'),'-o',str(cls.translate)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def shaders(self):
        with zipfile.ZipFile(ROOT/'game_backup2/patches/NFSMostWanted.WidescreenFix.zip')as z:module=z.read('scripts/NFSMostWanted.WidescreenFix.asi')
        self.assertEqual(hashlib.sha256(module).hexdigest(),'f3a7f8c04db295154e10987303a7237a8dc70e2ba944d38a79f895ad1f570dd1')
        pe=pefile.PE(data=module);entry=next(l.data.struct for t in pe.DIRECTORY_ENTRY_RESOURCE.entries if t.id==10 for n in t.directory.entries if n.id==201 for l in n.directory.entries)
        data=pe.get_data(entry.OffsetToData,entry.Size)
        self.assertEqual(hashlib.sha256(data).hexdigest(),'7d2afeb423986351704d3113910ed0d620e15215e78039811df3ff97dd28f974')
        found={}
        for off in range(0,len(data)-4,4):
            if struct.unpack_from('<I',data,off)[0]!=0xffff0300:continue
            cursor=off+4
            while cursor+4<=len(data):
                token=struct.unpack_from('<I',data,cursor)[0];opcode=token&65535
                if opcode==65535:
                    code=data[off:cursor+4]
                    for mode,value in ((1,.541901),(2,-.184189)):
                        if struct.pack('<f',value)in code:found[mode]=code
                    break
                if opcode==65534:cursor+=4*(1+((token>>16)&32767))
                elif opcode<=96:cursor+=4*(1+((token>>24)&15))
                else:break
        self.assertEqual(set(found),{1,2});return found
    def test_supplied_shader_identity(self):self.shaders()
    def test_com_snapshot_gating_reset_and_state(self):
        result=subprocess.run([str(self.com)],capture_output=True,text=True,timeout=15);self.assertEqual(result.returncode,0,result.stderr)
    def test_real_pixels_binary_curve_borders_order_queries_and_lifetime(self):
        paths=[]
        for mode,code in sorted(self.shaders().items()):
            binary=self.directory/f'gamma{mode}.bin';binary.write_bytes(code)
            translated=subprocess.run([str(self.translate),str(binary)],capture_output=True,check=True)
            source=self.directory/f'gamma{mode}.msl';source.write_bytes(translated.stdout);paths.append(str(source))
        result=subprocess.run([str(self.gpu),*paths],capture_output=True,text=True,timeout=40)
        if result.returncode==77:self.skipTest('Metal unavailable inside sandbox')
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('physical1600x1000 borders',result.stdout)
if __name__=='__main__':unittest.main()
