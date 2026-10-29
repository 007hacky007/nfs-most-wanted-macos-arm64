#include "hq_sync.h"
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
void guest_wait_begin(void),guest_wait_end(void);
typedef struct {uint32_t address;pthread_mutex_t mutex;pthread_cond_t condition;} Sync;
static Sync slots[64];
static pthread_mutex_t registry=PTHREAD_MUTEX_INITIALIZER;
static Sync *lookup(uint32_t address){
    if(!address){fprintf(stderr,"NULL ASI synchronization object\n");exit(78);}
    pthread_mutex_lock(&registry);Sync *slot=NULL;
    for(unsigned i=0;i<64;i++)if(slots[i].address==address){slot=&slots[i];break;}
    if(!slot)for(unsigned i=0;i<64;i++)if(!slots[i].address){slot=&slots[i];slot->address=address;
        pthread_mutex_init(&slot->mutex,NULL);pthread_cond_init(&slot->condition,NULL);break;}
    pthread_mutex_unlock(&registry);
    if(!slot){fprintf(stderr,"ASI synchronization table exhausted\n");exit(78);}return slot;
}
int hq_sync_call(CPU *c,const char *name,uint32_t *result){
    uint32_t a=MR32(c->esp);*result=0;
    if(!strcmp(name,"InitializeSListHead")){memset(g_mem+a,0,8);return 1;}
    if(!strcmp(name,"AcquireSRWLockExclusive")){
        Sync *slot=lookup(a);if(pthread_mutex_trylock(&slot->mutex)){
            guest_wait_begin();pthread_mutex_lock(&slot->mutex);guest_wait_end();}return 1;
    }
    if(!strcmp(name,"ReleaseSRWLockExclusive")){pthread_mutex_unlock(&lookup(a)->mutex);return 1;}
    if(!strcmp(name,"WakeAllConditionVariable")){pthread_cond_broadcast(&lookup(a)->condition);return 1;}
    if(!strcmp(name,"SleepConditionVariableSRW")){
        uint32_t lock=MR32(c->esp+4),ms=MR32(c->esp+8),flags=MR32(c->esp+12);
        if(flags){fprintf(stderr,"Unsupported ASI shared SRW condition wait\n");exit(78);}
        Sync *cv=lookup(a),*srw=lookup(lock);int status;
        struct timespec deadline;clock_gettime(CLOCK_REALTIME,&deadline);
        deadline.tv_sec+=ms/1000;deadline.tv_nsec+=(long)(ms%1000)*1000000;
        if(deadline.tv_nsec>=1000000000){deadline.tv_sec++;deadline.tv_nsec-=1000000000;}
        guest_wait_begin();
        status=ms==UINT32_MAX?pthread_cond_wait(&cv->condition,&srw->mutex):pthread_cond_timedwait(&cv->condition,&srw->mutex,&deadline);
        guest_wait_end();*result=status==0;if(status==ETIMEDOUT)MR32(c->fs_base+0x34)=1460;
        else if(status){fprintf(stderr,"ASI condition wait failed: %d\n",status);exit(78);}return 1;
    }
    return 0;
}
