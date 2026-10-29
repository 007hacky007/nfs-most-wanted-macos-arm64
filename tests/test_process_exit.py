from pathlib import Path
import subprocess
import tempfile
import unittest


class ProcessExitTests(unittest.TestCase):
    def test_worker_exit_never_uses_another_threads_jump_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'test.c').write_text('''#include <assert.h>
#include <pthread.h>
#include <setjmp.h>
#include <stdatomic.h>
#include <stdlib.h>
extern _Thread_local jmp_buf g_exit_jmp;
extern _Thread_local int g_exit_armed;
extern int g_exit_code;
void win32_process_exit(int);
static _Atomic int notifications,unlocks;
void lifecycle_guest_exited(int code){assert(code==17);notifications++;}
void guest_unlock(void){unlocks++;}
void discord_shutdown(void){}
static void *worker(void *unused){(void)unused;assert(!g_exit_armed);win32_process_exit(17);abort();}
int main(void){
if(!setjmp(g_exit_jmp)){g_exit_armed=1;win32_process_exit(42);abort();}
assert(g_exit_code==42&&!notifications&&!unlocks);
pthread_t thread;assert(!pthread_create(&thread,NULL,worker,NULL));
assert(!pthread_join(thread,NULL));assert(g_exit_armed&&g_exit_code==17&&notifications==1&&unlocks==1);
g_exit_armed=0;}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(root/'test.c'),'runtime/win32.c',
                            '-Wl,-dead_strip','-lm','-lz','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
