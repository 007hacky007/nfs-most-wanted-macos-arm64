from pathlib import Path
import subprocess
import tempfile
import unittest

class SyncTests(unittest.TestCase):
    def test_srw_wait_releases_lock_and_reacquires_after_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'test.c'
            source.write_text('''#include "cpu.h"
#include "hq_sync.h"
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
uint8_t *g_mem;static int notified;
void guest_wait_begin(void){}void guest_wait_end(void){}
static void *notify(void*x){(void)x;CPU cpu={0},*c=&cpu;c->esp=0x200;uint32_t r;
MR32(c->esp)=0x400;assert(hq_sync_call(c,"AcquireSRWLockExclusive",&r));notified=1;
MR32(c->esp)=0x800;assert(hq_sync_call(c,"WakeAllConditionVariable",&r));
MR32(c->esp)=0x400;assert(hq_sync_call(c,"ReleaseSRWLockExclusive",&r));return NULL;}
int main(void){g_mem=calloc(1,0x10000);CPU cpu={0},*c=&cpu;c->esp=0x100;c->fs_base=0x1000;uint32_t r;
MR32(c->esp)=0x400;assert(hq_sync_call(c,"AcquireSRWLockExclusive",&r));pthread_t thread;pthread_create(&thread,NULL,notify,NULL);
MR32(c->esp)=0x800;MR32(c->esp+4)=0x400;MR32(c->esp+8)=0xffffffff;MR32(c->esp+12)=0;
assert(hq_sync_call(c,"SleepConditionVariableSRW",&r)&&r&&notified);
MR32(c->esp+8)=1;assert(hq_sync_call(c,"SleepConditionVariableSRW",&r)&&!r&&MR32(c->fs_base+0x34)==1460);
MR32(c->esp)=0x400;assert(hq_sync_call(c,"ReleaseSRWLockExclusive",&r));pthread_join(thread,NULL);free(g_mem);}
''')
            subprocess.run(['clang','-O1','-pthread','-Iruntime',str(source),'runtime/hq_sync.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True,timeout=10)

if __name__=='__main__':unittest.main()
