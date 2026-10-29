"""Preparation accepts complete native captures and stops on repeated unknown states."""
import json
from pathlib import Path
import tempfile
import unittest


class PublicPreparationTests(unittest.TestCase):
    def test_mapped_image_uses_declared_virtual_size(self):
        from types import SimpleNamespace
        from tools.prepare_public_hq import mapped_image
        image=SimpleNamespace(OPTIONAL_HEADER=SimpleNamespace(SizeOfImage=16),
                              get_memory_mapped_image=lambda:bytes(range(20)))
        self.assertEqual(mapped_image(image),bytes(range(16)))
        image.get_memory_mapped_image=lambda:b'headers'
        self.assertEqual(mapped_image(image),b'headers'+bytes(9))

    def test_capture_failure_and_symlinks_are_rejected_before_use(self):
        from tools.prepare_public_hq import capture_images
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            record={'reason':'boot','game_base':0x400000,'game_size':16,'complete':True}
            image=root/'0001-boot.game.bin';image.write_bytes(bytes(16))
            meta=root/'0001-boot.json';meta.write_text(json.dumps(record))
            self.assertEqual(capture_images(root,16),[('boot',image)])
            record['complete']=False;meta.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'incomplete'):
                capture_images(root,16)
            record['complete']=True;meta.write_text(json.dumps(record));image.write_bytes(bytes(15))
            with self.assertRaisesRegex(ValueError,'size'):
                capture_images(root,16)
            image.unlink();image.symlink_to(meta)
            with self.assertRaisesRegex(ValueError,'symlink'):
                capture_images(root,16)

    def test_checkpoint_ranges_come_from_public_metadata(self):
        from tools.prepare_public_hq import checkpoint_ranges
        ranges=checkpoint_ranges()
        self.assertEqual(len(ranges),8)
        self.assertIn((0x6703d6,1),ranges)
        self.assertIn((0x7bb502,4),ranges)


if __name__=='__main__':unittest.main()
