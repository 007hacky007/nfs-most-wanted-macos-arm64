"""Only synthetic icon pixels are stored in these tests."""
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from tools import package_app


def synthetic_icon():
    bitmap=struct.pack('<IiiHHIIIIII',40,32,64,1,32,0,4096,0,0,0,0)
    bitmap+=bytes((255,64,0,255))*1024+bytes(128)
    return struct.pack('<HHHBBBBHHII',0,1,1,32,32,0,0,1,32,len(bitmap),22)+bitmap


def icon_resources():
    icon=synthetic_icon();bitmap=icon[22:]
    group=struct.pack('<HHHBBBBHHIH',0,1,1,32,32,0,0,1,32,len(bitmap),7)
    def branch(identifier,entries):return NS(id=identifier,directory=NS(entries=entries))
    def leaf(offset,data):return NS(data=NS(struct=NS(OffsetToData=offset,Size=len(data))))
    entries=[branch(3,[branch(7,[leaf(200,bitmap)])]),
             branch(14,[branch(101,[leaf(100,group)])])]
    data={100:group,200:bitmap}
    pe=NS(DIRECTORY_ENTRY_RESOURCE=NS(entries=entries),close=lambda:None,
          get_data=lambda offset,size:data[offset][:size])
    return pe,data


class AppIconTests(unittest.TestCase):
    def test_reconstructs_the_original_windows_icon(self):
        pe,_=icon_resources()
        with patch('tools.package_app.pefile.PE',return_value=pe):
            icon=package_app.windows_icon(Path('supplied/speed.exe'))
        self.assertEqual(icon,synthetic_icon())

    def test_missing_or_incomplete_resources_are_rejected(self):
        for kind in ('missing','short_group','short_image','missing_image'):
            with self.subTest(kind=kind):
                pe,data=icon_resources()
                if kind=='missing':pe.DIRECTORY_ENTRY_RESOURCE.entries=[]
                if kind=='short_group':data[100]=data[100][:-1]
                if kind=='short_image':data[200]=data[200][:-1]
                if kind=='missing_image':pe.DIRECTORY_ENTRY_RESOURCE.entries[0].directory.entries=[]
                with patch('tools.package_app.pefile.PE',return_value=pe):
                    with self.assertRaisesRegex(ValueError,'icon'):
                        package_app.windows_icon(Path('supplied/speed.exe'))

    @unittest.skipUnless(sys.platform=='darwin','requires native macOS icon conversion')
    def test_converts_to_icns_without_leaving_the_source_icon(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);output=root/'NFSMW.icns'
            package_app.write_app_icon(synthetic_icon(),output)
            data=output.read_bytes()
            self.assertEqual(data[:4],b'icns')
            self.assertEqual(struct.unpack_from('>I',data,4)[0],len(data))
            self.assertEqual(list(root.iterdir()),[output])


if __name__=='__main__':unittest.main()
