from pathlib import Path
import hashlib
import mmap
import os
import re
import struct
import subprocess
import tempfile
import unittest


SITES = [0x6ddd90, 0x6ddf2e, 0x6ddf94, 0x6ddfe6, 0x75597c, 0x74f3d1]
# TextureInfo records from the supplied ROCKPORT360 pack: width, height,
# mip count, DXT number, legacy first-mip size, actual payload size.
RECORDS = [(1360, 800, 11, 5, 1048576, 1451456),
           (1360, 800, 1, 1, 524288, 544000),
           (758, 1200, 11, 5, 1048576, 1217184),
           (1600, 2262, 12, 5, 4194304, 4831504)]

HARNESS = r'''
#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *g_mem, g_cbits[1u<<15];
guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
void mw_hdcontent_init(int);
int mw_hdcontent_hook(CPU*,uint32_t);
void guest_hook(CPU *c,uint32_t ip){mw_hdcontent_hook(c,ip);}
static unsigned sizes[16], offsets[16], widths[16], heights[16];
static unsigned skip, count, level, copied, failures, enabled;
static void ret(CPU *c,unsigned args){c->eip=MR32(c->esp);c->esp+=4+args;c->eax=0;}
void sub_00460d60(CPU *c){ret(c,0);c->eax=1;}
void sub_006d99c0(CPU *c){(void)c;assert(0);}
void sub_00652ad0(CPU *c){(void)c;assert(0);}
void sub_00652b10(CPU *c){(void)c;assert(0);}
void dispatch_indirect(CPU *c,uint32_t ip){
    if(ip==0xf0000000){
        if(MR32(c->esp+8)!=widths[skip] || MR32(c->esp+12)!=heights[skip])failures++;
        assert(MR32(c->esp+16)==count-skip);
        MR32(MR32(c->esp+32))=0x4000;ret(c,36);
    }else if(ip==0xf0000004){
        level=MR32(c->esp+8)+skip;
        unsigned out=MR32(c->esp+12);
        memset(g_mem+0x2000000,0xa5,0x800000);
        MR32(out)=((widths[level]+3)/4)*16;MR32(out+4)=0x2000000;
        ret(c,20);
    }else if(ip==0xf0000008){
        if(memcmp(g_mem+0x2000000,g_mem+0x1000000+offsets[level],sizes[level]))failures++;
        for(unsigned i=0;i<64;i++)if(MR8(0x2000000+sizes[level]+i)!=0xa5){failures++;break;}
        copied++;ret(c,8);
    }else{fprintf(stderr,"unexpected dispatch %x\n",ip);abort();}
}
'''


class HDContentTests(unittest.TestCase):
    def test_disabled_diagnostics_do_not_walk_guest_memory(self):
        body = r'''
int main(void){
    /* Committed addresses without backing memory make any diagnostic read
     * fail, proving the disabled path stops before its pointer walk. */
    memset(g_cbits,255,sizeof g_cbits);
    CPU cpu={0},*c=&cpu;c->esp=0x9000;c->edi=0x40b0;c->esi=0x3000;
    CPU before=*c;mw_hdcontent_init(1);
    assert(mw_hdcontent_hook(c,0x75597c));
    assert(mw_hdcontent_hook(c,0x74f3d1));
    assert(!memcmp(c,&before,sizeof *c));return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'disabled.c';source.write_text(HARNESS+body)
            binary=Path(tmp)/'disabled'
            build=subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/mw_hdcontent.c',
                                  '-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            for value in (None,'','0','false'):
                env=dict(os.environ);env.pop('NFSMW_HD_DIAGNOSTICS',None)
                if value is not None:env['NFSMW_HD_DIAGNOSTICS']=value
                result=subprocess.run([str(binary)],capture_output=True,text=True,env=env)
                self.assertEqual(result.returncode,0,(value,result.stderr))
                self.assertEqual(result.stderr,'')

    def test_missing_solid_diagnostic_is_bounded_and_preserves_cpu(self):
        body = r'''
int main(void){
    g_mem=calloc(1,0x10000);assert(g_mem);g_cbits[0]=15;
    CPU cpu={0},*c=&cpu;c->esp=0x9000;c->edi=0x3000;c->esi=0x2000;
    c->eax=123;c->ecx=456;c->cf=1;c->zf=1;c->st[0]=1.25;
    MR32(0x3084)=0x4000;MR32(0x4000)=7;
    MR32(c->esp+0x2c)=0x3dc6a1f4;MR32(c->esp+0x14)=2;MR32(c->esp+0x18)=2;
    CPU before=*c;uint8_t memory[0x10000];memcpy(memory,g_mem,sizeof memory);
    mw_hdcontent_init(0);assert(mw_hdcontent_hook(c,0x75597c));
    mw_hdcontent_init(1);MR32(0x200c)=1;assert(mw_hdcontent_hook(c,0x75597c));MR32(0x200c)=0;
    for(unsigned i=0;i<40;i++)assert(mw_hdcontent_hook(c,0x75597c));
    assert(!memcmp(c,&before,sizeof *c));assert(!memcmp(memory,g_mem,sizeof memory));
    MR32(c->esp+0x14)=66;MR32(c->esp+0x28)=0xabcdef00;
    before=*c;memcpy(memory,g_mem,sizeof memory);
    for(unsigned i=0;i<40;i++)assert(mw_hdcontent_hook(c,0x75597c));
    assert(!memcmp(c,&before,sizeof *c));assert(!memcmp(memory,g_mem,sizeof memory));
    c->esi=0x3000;c->edi=0x40b0;c->ecx=0;MR32(c->esp+4)=0x12345000;
    before=*c;memcpy(memory,g_mem,sizeof memory);
    for(unsigned i=0;i<40;i++)assert(mw_hdcontent_hook(c,0x74f3d1));
    assert(!memcmp(c,&before,sizeof *c));assert(!memcmp(memory,g_mem,sizeof memory));
    free(g_mem);return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'diagnostic.c';source.write_text(HARNESS+body)
            binary=Path(tmp)/'diagnostic'
            build=subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/mw_hdcontent.c',
                                  '-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,
                                  env={**os.environ,'NFSMW_HD_DIAGNOSTICS':'1'})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stderr.count('Missing car solid:'),16)
            self.assertIn('car=7 hash=3dc6a1f4 slot=2 lod=2 render=00003000 model=00002000',result.stderr)
            self.assertEqual(result.stderr.count('Missing wheel solid:'),16)
            self.assertIn('car=7 hash=3dc6a1f4 slot=66 lod=2 render=00003000 model=00002000 part=abcdef00',result.stderr)
            self.assertEqual(result.stderr.count('Missing front wheel at light-material call:'),16)
            self.assertIn('car=7 lod=1 render=00003000 wheel_slot=000040b0 material=12345000',result.stderr)

    def test_wheel_stream_snapshot_is_read_only_and_bounded(self):
        body = r'''
int main(void){
    g_mem=calloc(1,0xa00000);assert(g_mem);memset(g_cbits,0,sizeof g_cbits);
    for(unsigned p=0;p<0xa00000;p+=16384)g_cbits[(p>>14)>>3]|=1<<((p>>14)&7);
    CPU cpu={0},*c=&cpu;c->esp=0x9000;c->edi=0x3000;c->esi=0x2000;
    c->cf=1;c->zf=1;c->st[0]=1.25;
    MR32(0x3084)=0x6000;MR32(0x6000)=60;
    MR32(0x4628)=0;MR32(0x462c)=3;
    MR32(0x6008)=0;MR32(0x600c)=0;MR32(0x6010)=1;MR32(0x6014)=3;
    MR32(c->esp+0x2c)=0x0e13d8bc;MR32(c->esp+0x14)=66;MR32(c->esp+0x18)=1;
    MR32(0x91a078)=0x10000;MR32(0x10000)=0x91a078;
    MR32(0x10024)=0x11000;MR32(0x10028)=3;MR32(0x1002c)=2;
    MR32(0x11000)=0x0e13d8bb;MR32(0x11018)=0x0e13d8bc;MR32(0x11030)=0x0e13d8bd;
    MR8(0x11029)=0x10;MR16(0x1102a)=1;MR32(0x1102c)=0x20000;
    MR32(0x91a060)=128;MR32(0x20000)=0x80134010;MR32(0x20008)=0x134011;
    MR32(0x20020)=0x0e13d8bc;MR8(0x2001d)=1;
    MR32(0x1003c)=0x12000;MR32(0x1200c)=1;MR32(0x12074)=0x13000;
    MR32(0x13000)=0x0e13d8bc;MR32(0x13004)=0x20010;
    MR8(0x9175dc+(0x0e13d8bc&8191))=3;
    CPU before=*c;uint8_t *memory=malloc(0xa00000);assert(memory);memcpy(memory,g_mem,0xa00000);
    mw_hdcontent_init(1);mw_hdcontent_hook(c,0x75597c);
    assert(!memcmp(c,&before,sizeof *c));assert(!memcmp(memory,g_mem,0xa00000));
    /* Corrupt list cycles and counts remain bounded and never call guest code. */
    MR32(0x10000)=0x10000;MR32(0x10028)=0xffffffff;
    memcpy(memory,g_mem,0xa00000);mw_hdcontent_hook(c,0x75597c);
    assert(!memcmp(c,&before,sizeof *c));assert(!memcmp(memory,g_mem,0xa00000));
    free(memory);free(g_mem);return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'snapshot.c';source.write_text(HARNESS+body)
            binary=Path(tmp)/'snapshot'
            build=subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/mw_hdcontent.c',
                                  '-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5,
                                  env={**os.environ,'NFSMW_HD_DIAGNOSTICS':'1'})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('render_lods=0:3 ride_lods=0:0/1:3',result.stderr)
            self.assertIn('stream_record=00010000 entry=00011018 flags=10 refs=1 buffer=00020000 pending=2',result.stderr)
            self.assertIn('payload_tag=80134010 payload_hash=0e13d8bc initialized=1 registry=00020010 bloom=3',result.stderr)
            self.assertIn('stream=unresolved scanned=64',result.stderr)

    def test_stock_other_formats_invalid_spans_and_metadata_are_unchanged(self):
        body = r'''
int main(void){
    g_mem=calloc(1,0x3000000);assert(g_mem);memset(g_cbits,255,sizeof g_cbits);
    CPU cpu={0},*c=&cpu;
    for(unsigned test=0;test<12;test++){
        memset(g_mem+0x2000,0,0x2000);memset(g_cbits,255,sizeof g_cbits);
        MR32(0x3000)=0x2000;MR32(0x2014)=0x35545844;
        MR16(0x3044)=758;MR16(0x3046)=1200;MR8(0x304e)=11;
        MR32(0x3038)=1217184;MR32(0x3070)=0x1000000;
        mw_hdcontent_init(test!=0);
        switch(test){
        case 1:MR32(0x2014)=21;break;
        case 2:MR32(0x2014)=41;break;
        case 3:MR16(0x3044)=1024;MR16(0x3046)=1024;MR8(0x304e)=1;MR32(0x3038)=1048576;break;
        case 4:MR32(0x3038)--;break;
        case 5:MR8(0x304e)=17;break;
        case 6:MR8(0x304e)=0;break;
        case 7:MR16(0x3044)=0;break;
        case 8:MR32(0x3070)=0xfffff000;break;
        case 9:g_cbits[(0x1004000>>14)>>3]&=~(1<<((0x1004000>>14)&7));break;
        case 10:MR32(0x3000)=0;break;
        case 11:MR16(0x3044)=40000;break;
        }
        c->esp=0x9000;c->ecx=0x3000;CPU before=*c;
        assert(mw_hdcontent_hook(c,0x6ddd90));assert(!memcmp(c,&before,sizeof *c));
        c->esp-=0x34;c->ebp=1;c->ebx=0;c->eax=999;
        unsigned w=MR16(0x3044),h=MR16(0x3046);before=*c;
        mw_hdcontent_hook(c,0x6ddf2e);mw_hdcontent_hook(c,0x6ddf94);mw_hdcontent_hook(c,0x6ddfe6);
        assert(!memcmp(c,&before,sizeof *c));assert(MR16(0x3044)==w&&MR16(0x3046)==h);
    }
    assert(!mw_hdcontent_hook(c,0x123456));free(g_mem);return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'validation.c';source.write_text(HARNESS+body)
            binary=Path(tmp)/'validation'
            build=subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/mw_hdcontent.c',
                                  '-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(os.environ.get('NFSMW_HQ_PACK'), 'set NFSMW_HQ_PACK to inspect supplied payload')
    def test_supplied_payload_has_exact_tightly_packed_mip_lengths(self):
        expected = dict(zip(('_ADS_AXEB_BB_A_EA', '_ADS_FITNESSB_BB_EA',
                             '_OBJ_MOVIEPOSTERKONO_JF', '_OBJ_MOVIEPOSTEROCTO_JF'), RECORDS))
        found = {}
        path = Path(os.environ['NFSMW_HQ_PACK'])/'textures.bin'
        with path.open('rb') as file, mmap.mmap(file.fileno(),0,access=mmap.ACCESS_READ) as data:
            def chunks(start, end):
                while start < end:
                    kind,size=struct.unpack_from('<II',data,start)
                    self.assertLessEqual(start+8+size,end)
                    yield kind,start+8,start+8+size
                    start+=8+size
                self.assertEqual(start,end)
            for kind,start,end in chunks(0,len(data)):
                if kind != 0xb3300000:
                    continue
                parts={kind:(a,b) for kind,a,b in chunks(start,end)}
                if 0xb3310000 not in parts or 0xb3320000 not in parts:
                    continue
                meta={kind:(a,b) for kind,a,b in chunks(*parts[0xb3310000])}
                pixels={kind:(a,b) for kind,a,b in chunks(*parts[0xb3320000])}
                if 0x33310004 not in meta:
                    continue
                infos,info_end=meta[0x33310004];renderers,_=meta[0x33310005]
                payload,payload_end=pixels[0x33320002]
                for index,info in enumerate(range(infos,info_end,124)):
                    name=data[info+12:info+36].split(b'\0')[0].decode('ascii')
                    if name not in expected:
                        continue
                    w,h=struct.unpack_from('<HH',data,info+0x44)
                    count=data[info+0x4e];fmt=struct.unpack_from('<I',data,renderers+index*32+20)[0]
                    offset,total=struct.unpack_from('<I',data,info+0x30)[0],struct.unpack_from('<I',data,info+0x38)[0]
                    first=struct.unpack_from('<I',data,info+0x40)[0];dxt=(fmt>>24)-48
                    found[name]=(w,h,count,dxt,first,total)
                    sizes=[((max(w>>m,1)+3)//4)*((max(h>>m,1)+3)//4)*(8 if dxt==1 else 16) for m in range(count)]
                    self.assertEqual(sum(sizes),total,name)
                    self.assertLessEqual(payload+offset+total,payload_end,name)
            self.assertEqual(found,expected)

    @unittest.skipUnless(Path('game/speed.exe').is_file(), 'requires supported executable')
    def test_real_loader_copies_complete_npot_mips_without_overwrite(self):
        from tools.lift import Lifter
        image = Path('game/speed.exe').read_bytes()
        self.assertEqual(hashlib.sha256(image).hexdigest(),
                         '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        code, _ = Lifter('game/speed.exe', hooks=SITES).lift(0x6ddd90)
        body = r'''
int main(int argc,char **argv){
    assert(argc==9);enabled=atoi(argv[1]);unsigned w=atoi(argv[2]),h=atoi(argv[3]);
    count=atoi(argv[4]);unsigned dxt=atoi(argv[5]),first=atoi(argv[6]),total=atoi(argv[7]);
    skip=atoi(argv[8]);if(skip>=count)skip=count-1;
    g_mem=calloc(1,0x3000000);assert(g_mem);memset(g_cbits,255,sizeof g_cbits);
    unsigned bytes=0;
    for(unsigned i=0;i<count;i++){
        widths[i]=w;heights[i]=h;offsets[i]=bytes;
        sizes[i]=((w+3)/4)*((h+3)/4)*(dxt==1?8:16);bytes+=sizes[i];
        w=w>1?w/2:1;h=h>1?h/2:1;
    }
    assert(bytes==total);
    for(unsigned i=0;i<0x800000;i++)MR8(0x1000000+i)=(i*17+(i>>8)*31)%251;
    MR32(0x3000)=0x2000;MR32(0x2014)=0x30545844u+(dxt<<24);
    MR16(0x3044)=widths[0];MR16(0x3046)=heights[0];MR8(0x304e)=count;
    MR32(0x3040)=first;MR32(0x3038)=total;MR32(0x3070)=0x1000000;
    MR32(0x982ae0)=atoi(argv[8]);MR32(0x982bdc)=0x6000;
    MR32(0x6000)=0x7000;MR32(0x705c)=0xf0000000;
    MR32(0x4000)=0x5000;MR32(0x504c)=0xf0000004;MR32(0x5050)=0xf0000008;
    MR32(0x987ec4)=0x987ec0;
    CPU cpu={0},*c=&cpu;c->esp=0x9000;c->ecx=0x3000;MR32(c->esp)=0x12345678;
    mw_hdcontent_init(enabled);sub_006ddd90(c);
    assert(c->esp==0x9004&&c->eip==0x12345678);assert(copied==count-skip);
    printf("%u\n",failures);free(g_mem);return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'loader.c';source.write_text(HARNESS+code+body)
            binary=Path(tmp)/'loader'
            build=subprocess.run(['clang','-O1','-Iruntime',str(source),
                                  'runtime/mw_hdcontent.c','-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            # Disabled hooks reproduce the existing overwrite/offset bug.
            for record in RECORDS + [(9, 3, 4, 3, 64, 96)]:
                for skip in (0,1,3,99):
                    for enabled in (0,1):
                        with self.subTest(record=record,skip=skip,enabled=enabled):
                            args=[enabled,*record,skip]
                            run=subprocess.run([str(binary),*map(str,args)],capture_output=True,text=True)
                            self.assertEqual(run.returncode,0,run.stderr)
                            failures=int(run.stdout)
                            self.assertEqual(failures==0,bool(enabled),run.stdout)

    def test_hook_markers_cover_the_texture_loader_and_model_diagnostics(self):
        source=Path('runtime/mw_hdcontent.c').read_text()
        sites={int(a,16) for a in re.findall(r'HOOK_SITE\((0x[0-9a-fA-F]+)\)',source)}
        self.assertEqual(sites,set(SITES))


if __name__ == '__main__':
    unittest.main()
