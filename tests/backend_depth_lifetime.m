/* Deterministic CPU-only check of the actual depth alias publication/sweep. */
#include <pthread.h>
#include <stdatomic.h>
#include <signal.h>
#include <unistd.h>
#include <assert.h>
static pthread_mutex_t barrier=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static void *watched_dead;
static int claimed,resume_sweep,publisher_entered,publisher_done;
static _Thread_local int publishing;
static void after_exchange(void *operand){
    if(operand!=watched_dead)return;
    pthread_mutex_lock(&barrier);claimed=1;pthread_cond_broadcast(&changed);
    while(!resume_sweep)pthread_cond_wait(&changed,&barrier);
    pthread_mutex_unlock(&barrier);
}
static int observe_production_lock(pthread_mutex_t *mutex){
    if(publishing){
        pthread_mutex_lock(&barrier);publisher_entered=1;pthread_cond_broadcast(&changed);
        pthread_mutex_unlock(&barrier);
    }
    return pthread_mutex_lock(mutex);
}
#undef atomic_exchange
#define atomic_exchange(pointer,value) ({ __auto_type test_pointer=(pointer); \
    __auto_type test_old=__c11_atomic_exchange(test_pointer,(value),memory_order_seq_cst); \
    after_exchange((void*)test_pointer);test_old; })
#define pthread_mutex_lock observe_production_lock
#include "../runtime/metal.m"
#undef pthread_mutex_lock
#undef atomic_exchange
int g_perflog;_Atomic int g_pl_thumb_req;char g_pl_dir[900];_Atomic long g_mw_dump_frame;
int g_texrep_frame_on;__strong id<MTLTexture>g_texrep_tex[TEXREP_MAXTEX];uint8_t g_texrep_k[TEXREP_MAXTEX];
static __strong id<MTLTexture> new_image;
static void *sweep_worker(void *unused){(void)unused;@autoreleasepool{z_sweep_dead();}return NULL;}
static void *publish_worker(void *unused){
    (void)unused;publishing=1;@autoreleasepool{z_publish_texture(2,new_image);}
    pthread_mutex_lock(&barrier);publisher_done=1;pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&barrier);return NULL;
}
static void timeout(int signal){(void)signal;_exit(90);}
int main(void){@autoreleasepool{
    signal(SIGALRM,timeout);alarm(10);
    id<MTLTexture> old_image=(id<MTLTexture>)[NSObject new];
    new_image=(id<MTLTexture>)[NSObject new];
    g_ztex[2]=old_image;atomic_store(&g_zdead[2],1);atomic_store(&g_zsweep_at,1);
    atomic_store(&g_frames_drawn,1);watched_dead=&g_zdead[2];
    pthread_t sweeper,publisher;assert(!pthread_create(&sweeper,NULL,sweep_worker,NULL));
    pthread_mutex_lock(&barrier);
    while(!claimed)pthread_cond_wait(&changed,&barrier);
    pthread_mutex_unlock(&barrier);
    assert(!pthread_create(&publisher,NULL,publish_worker,NULL));
    pthread_mutex_lock(&barrier);
    /* Unlocked code publishes first. Locked code announces its blocked attempt. */
    while(!publisher_entered&&!publisher_done)pthread_cond_wait(&changed,&barrier);
    resume_sweep=1;pthread_cond_broadcast(&changed);pthread_mutex_unlock(&barrier);
    assert(!pthread_join(sweeper,NULL)&&!pthread_join(publisher,NULL));
    assert(g_ztex[2]==new_image);assert(!atomic_load(&g_zdead[2]));
    assert(atomic_load(&g_zforget[2])==2);
    puts("PASS actual depth sweep/publication interleaving; no Metal device or GPU work");
    return 0;
}}
