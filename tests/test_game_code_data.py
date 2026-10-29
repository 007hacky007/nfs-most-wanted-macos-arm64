import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_hq_module_catalog import fixture_dll
from tools.lift import RawLifter, Lifter
from capstone.x86 import X86_REG_EDX


def synthetic_switches():
    base=0x6d7500;data=bytearray(b'\x90'*0x180)
    def put(address,code):data[address-base:address-base+len(code)]=code
    def jump(address,target):put(address,b'\xe9'+struct.pack('<i',target-address-5))
    jump(base,0x6d7533)
    for compare,lookup,branch,table,index,default in (
        (0x6d7533,0x6d7538,0x6d753f,0x6d7624,0x6d762c,0x6d758d),
        (0x6d75b2,0x6d75b7,0x6d75be,0x6d7640,0x6d7648,0x6d75de)):
        put(compare,b'\x83\xf8\x12\x77'+bytes([default-compare-5]))
        put(lookup,b'\x0f\xb6\x80'+struct.pack('<I',index))
        put(branch,b'\xff\x24\x85'+struct.pack('<I',table))
        put(index,bytes([0,1]*9+[0]))
    for at in (0x6d7546,0x6d758d):jump(at,0x6d75b2)
    for at in (0x6d75c5,0x6d75de):jump(at,0x6d7622)
    put(0x6d7622,b'\xc3')
    put(0x6d7624,struct.pack('<II',0x6d7546,0x6d758d))
    put(0x6d7640,struct.pack('<II',0x6d75c5,0x6d75de))
    return bytes(data)


class GameCodeDataTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.game_code_data'),
                             'bounded data-root metadata is missing')
        from tools import game_code_data
        return game_code_data

    def test_hash_gate_and_verified_switch_structure(self):
        api=self.api();data=synthetic_switches()
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'synthetic';exe.write_bytes(data)
            self.assertEqual(api.relocation_data_ranges(exe,None),())
            with patch.object(api,'CANONICAL_SHA',hashlib.sha256(data).hexdigest()), \
                    patch.object(api,'SWITCHES',tuple(s for s in api.SWITCHES if s.owner==0x6d7500)):
                ranges=api.relocation_data_ranges(exe,RawLifter(data,base=0x6d7500))
                self.assertEqual(ranges,((0x6d7624,0x6d762c),(0x6d762c,0x6d763f),
                                         (0x6d7640,0x6d7648),(0x6d7648,0x6d765b)))
                for at in (0x6d7535,0x6d753b,0x6d7542,0x6d7624,0x6d762c,0x6d7622):
                    changed=bytearray(data);changed[at-0x6d7500]^=3
                    with self.subTest(address=at),self.assertRaisesRegex(ValueError,'code data'):
                        api.relocation_data_ranges(exe,RawLifter(changed,base=0x6d7500))

    def test_discovery_filters_only_relocation_roots(self):
        self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=bytearray(fixture_dll());base=0x10001000
            # Entry calls a data-range address. An explicit seed also lies in the range.
            data[0x200:0x206]=bytes.fromhex('e81b000000c3')
            for offset in (0x20,0x30,0x40,0x80):data[0x200+offset]=0xc3
            for offset,target in ((0x100,base+0x20),(0x104,base+0x30),
                                  (0x108,base+0x40),(0x10c,base+0x80)):
                struct.pack_into('<I',data,0x200+offset,target)
            exe=root/'fixture.exe';exe.write_bytes(data)
            relocs=root/'relocs';relocs.write_text(''.join(f'{base+offset:x}\n' for offset in (0x100,0x104,0x108,0x10c)))
            seeds=root/'seeds';seeds.write_text(f'{base+0x30:x}\n')
            with patch.object(sys,'argv',['genall.py',str(exe),'1']),patch.dict(os.environ,
                    {'GENOUT':str(root/'gen'),'RELOCS':str(relocs),'SEEDS':str(seeds),
                     'CODE_RVA_START':'','LREGS':'0','BRANCH_HOOKS':''}):
                spec=importlib.util.spec_from_file_location('data_root_generator','tools/genall.py')
                generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
            # The mocked proof result isolates discovery policy; the preceding test exercises real decoding.
            with patch.object(generator,'relocation_data_ranges',return_value=((base,base+0x50),)):
                functions,fixed,refs=generator.discover_all()
            self.assertEqual(functions,[base,base+0x20,base+0x30,base+0x80])
            self.assertTrue({base,base+0x20,base+0x30}<=fixed)
            self.assertNotIn(base+0x40,refs)
            self.assertIn(base+0x80,refs)

    def test_direct_tables_and_index_maps_with_different_registers(self):
        api=self.api();base=0x401000
        for indexed in (False,True):
            with self.subTest(indexed=indexed),tempfile.TemporaryDirectory() as tmp:
                data=bytearray(b'\xcc'*0x60)
                code=(bytes.fromhex('83fb01773b0fb6934c104000ff249544104000') if indexed
                      else bytes.fromhex('83f901773bff248d44104000'))
                data[:len(code)]=code
                for offset in (0x20,0x30,0x40):data[offset]=0xc3
                struct.pack_into('<II',data,0x44,base+0x20,base+0x30)
                data[0x4c:0x4e]=b'\x00\x01'
                switch=api.Switch(base,base+0x40,base+3,base+(12 if indexed else 5),
                    base+0x44,(base+0x20,base+0x30),base+0x4c if indexed else 0,2 if indexed else 0)
                exe=Path(tmp)/'synthetic';exe.write_bytes(data)
                with patch.object(api,'CANONICAL_SHA',hashlib.sha256(data).hexdigest()), \
                        patch.object(api,'SWITCHES',(switch,)):
                    ranges=api.relocation_data_ranges(exe,RawLifter(data,base=base))
                    self.assertEqual(ranges,((base+0x44,base+0x4c),(base+0x4c,base+0x4e)) if indexed
                                     else ((base+0x44,base+0x4c),))

    def test_register_limit_requires_the_verified_load_and_compare(self):
        api=self.api();base=0x6c69cd
        exe=Path(os.environ.get('NFSMW_CANONICAL_IMAGE','out/installed/.nfsmw/runtime.exe'))
        if not exe.is_file():self.skipTest('optional canonical binary is unavailable')
        self.assertEqual(hashlib.sha256(exe.read_bytes()).hexdigest(),api.CANONICAL_SHA)
        import pefile
        data=pefile.PE(str(exe)).get_data(base-0x400000,15)
        lifter=RawLifter(data,base=base)
        block=list(lifter.md.disasm(data,base))
        self.assertEqual(api.register_bound(lifter,block),(X86_REG_EDX,5,0x6c69dc))
        for offset in (1,6,8,13):
            changed=bytearray(data);changed[offset]^=3
            block=list(lifter.md.disasm(changed,base))
            self.assertIsNone(api.register_bound(lifter,block))

    def test_available_canonical_binary_matches_metadata(self):
        api=self.api()
        exe=Path(os.environ.get('NFSMW_CANONICAL_IMAGE','out/installed/.nfsmw/runtime.exe'))
        if not exe.is_file():self.skipTest('optional canonical binary is unavailable')
        if hashlib.sha256(exe.read_bytes()).hexdigest()!=api.CANONICAL_SHA:
            self.skipTest('optional binary is not canonical')
        ranges=api.relocation_data_ranges(exe,Lifter(str(exe)))
        self.assertEqual(sum(end-start for start,end in ranges),283)
        for address in (0x601f78,0x6c6ca0,0x6d645c,0x6d792c,0x6e0a9c,0x7a5f28,0x7b4570):
            self.assertTrue(any(start<=address<end for start,end in ranges),hex(address))
        for address in (0x6e0329,0x6e042e,0x6d7546,0x6d758d):
            self.assertFalse(any(start<=address<end for start,end in ranges),hex(address))


if __name__=='__main__':unittest.main()
