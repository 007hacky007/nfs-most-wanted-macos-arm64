from pathlib import Path
import re
import subprocess
import tempfile
import unittest

class ConfigTests(unittest.TestCase):
    def test_x360_strict_fields_and_xenon_optional_overrides_are_atomic(self):
        fields=re.findall(r'\{"([^"]+)","([^"]+)",0x[0-9a-f]+,\'([bifs])\'\}',Path('runtime/hq_config_fields.h').read_text())
        self.assertEqual(len(fields),33)
        lines=[]
        for section,key,kind in fields:
            value={'b':'1','i':'-2','f':'0.92','s':'fixture'}[kind]
            lines.extend((f'[{section}]',f'{key} = {value}'))
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);good=root/'x360.ini';good.write_text('\n'.join(lines)+'\n')
            bad=root/'bad.ini';bad.write_text(good.read_text().replace('FEScale = 0.92','FEScale = nan'))
            xenon=root/'xenon.ini';xenon.write_text('[MAIN]\nTexturePack = particles.bin\nContrails = 0\n[Limits]\nSparkIntensity = 0.75\nMaxParticles = 200\nCGIntensityBehavior = 1\n')
            badx=root/'badx.ini';badx.write_text('[Limits]\nSparkIntensity = nan\n')
            code=root/'config.c';code.write_text('''#include "hq_config.h"
#include <assert.h>
#include <string.h>
int main(int n,char**v){assert(n==5);uint8_t x[HQ_CONFIG_SIZE],before[HQ_CONFIG_SIZE];
assert(hq_config_load(v[1],x));float f;memcpy(&f,x+0x14,4);assert(f>0.919f&&f<0.921f);assert(x[0]==1&&!strcmp((char*)x+0x31,"fixture"));
memcpy(before,x,sizeof x);assert(!hq_config_load(v[2],x)&&!memcmp(before,x,sizeof x));
uint8_t y[HQ_XENON_CONFIG_SIZE],old[HQ_XENON_CONFIG_SIZE];uint64_t present=0;
assert(hq_config_xenon_load(v[3],y,&present));assert(!strcmp((char*)y+0xd0,"particles.bin")&&y[0xbb]==0);
memcpy(&f,y+0xbc,4);assert(f==0.75f);assert((present&(1ull<<10))==0);assert((present&(1ull<<16))!=0);
memcpy(old,y,sizeof y);uint64_t oldmask=present;assert(!hq_config_xenon_load(v[4],y,&present));assert(present==oldmask&&!memcmp(old,y,sizeof y));}
''')
            result=subprocess.run(['clang','-O1','-Iruntime',str(code),'runtime/hq_config.c','-o',str(root/'config')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'config'),str(good),str(bad),str(xenon),str(badx)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
