/* Type 9 occlusion queries. g_qlock protects objects, generations and frames.
 * Each recorded frame owns references until its GPU completion. A new BEGIN
 * never allows an old completion to overwrite the new generation's result.
 * Partial-frame FLUSH is unsupported: this renderer submits only at Present. */
#define MQ_INVALID 0x8876086cu
#define MQ_UNAVAILABLE 0x8876086au
#define MQ_LOST 0x88760868u
#define MQ_OOM 0x8007000eu
#define MQ_MAX 512u
#define MQ_FRAME_MAX 64u
typedef struct MQRun { unsigned refs,pending,queued,ended; uint32_t error; uint64_t samples; struct MQRun *next; } MQRun;
typedef struct { unsigned handle,lost; MQRun *run; } MQObject;
typedef struct { unsigned count; MQRun *run[MQ_FRAME_MAX]; } MQFrame;
typedef struct { MQFrame frame; unsigned draws,failed; uint64_t masks[]; } MQSubmission;
static MQObject g_mquery[MQ_MAX];
static MQFrame g_mqframe[2];
static MQRun *g_mqactive;
static unsigned g_mqserial;
static void mq_release(MQRun *run){if(run && !--run->refs)free(run);}
static void mq_unlink(MQRun *run){MQRun **p=&g_mqactive;while(*p){if(*p==run){*p=run->next;return;}p=&(*p)->next;}}
static MQObject *mq_object(unsigned handle){MQObject *q=&g_mquery[handle%MQ_MAX];return handle && q->handle==handle?q:NULL;}
static int mq_frame_add(int b,MQRun *run){
    MQFrame *f=&g_mqframe[b];for(unsigned i=0;i<f->count;i++)if(f->run[i]==run)return (int)i;
    if(f->count==MQ_FRAME_MAX){run->error=MQ_OOM;return -1;}
    unsigned i=f->count++;f->run[i]=run;run->refs++;run->pending++;run->queued++;return (int)i;
}
static uint64_t mq_snapshot(int b){
    uint64_t mask=0;for(MQRun *r=g_mqactive;r;r=r->next){int i=mq_frame_add(b,r);if(i>=0)mask|=1ull<<i;}
    return mask;
}
unsigned metal_query_create(void){
    pthread_mutex_lock(&g_qlock);unsigned handle=0;
    for(unsigned i=0;i<MQ_MAX;i++){unsigned n=++g_mqserial;if(!n)n=++g_mqserial;
        if(!g_mquery[n%MQ_MAX].handle){g_mquery[n%MQ_MAX].handle=n;handle=n;break;}}
    pthread_mutex_unlock(&g_qlock);return handle;
}
void metal_query_destroy(unsigned handle){
    pthread_mutex_lock(&g_qlock);MQObject *q=mq_object(handle);
    if(q){mq_unlink(q->run);mq_release(q->run);memset(q,0,sizeof *q);}pthread_mutex_unlock(&g_qlock);
}
uint32_t metal_query_issue(unsigned handle,unsigned flags){
    uint32_t status=0;pthread_mutex_lock(&g_qlock);MQObject*q=mq_object(handle);
    if(!q || (flags!=1 && flags!=2))status=MQ_INVALID;
    else if(q->lost)status=MQ_LOST;
    else if(q->run && q->run->error)status=q->run->error;
    else if(flags==2){
        MQRun *run=calloc(1,sizeof *run);
        if(!run)status=MQ_OOM;
        else{run->refs=1;mq_unlink(q->run);mq_release(q->run);q->run=run;
            run->next=g_mqactive;g_mqactive=run;if(mq_frame_add(g_cur,run)<0)status=run->error;}
    }else if(!q->run || q->run->ended)status=MQ_INVALID;
    else{if(mq_frame_add(g_cur,q->run)<0)status=q->run->error;q->run->ended=1;mq_unlink(q->run);}
    pthread_mutex_unlock(&g_qlock);return status;
}
uint32_t metal_query_get_data(unsigned handle,unsigned flags,uint32_t *value){
    uint32_t status=0;pthread_mutex_lock(&g_qlock);MQObject*q=mq_object(handle);
    if(!q || flags>1)status=MQ_INVALID;
    else if(q->lost)status=MQ_LOST;
    else if(q->run){MQRun*r=q->run;
        if(r->error)status=r->error;
        else if(!r->ended)status=MQ_INVALID;
        else if(flags && r->queued)status=MQ_UNAVAILABLE;
        else if(r->pending)status=1; /* S_FALSE, leave output untouched */
        else if(value)*value=r->samples>UINT32_MAX?UINT32_MAX:(uint32_t)r->samples;
    }else if(value)*value=0;
    pthread_mutex_unlock(&g_qlock);return status;
}
void metal_query_reset(void){
    pthread_mutex_lock(&g_qlock);g_mqactive=NULL;
    for(unsigned i=0;i<MQ_MAX;i++)if(g_mquery[i].handle){
        g_mquery[i].lost=1;if(g_mquery[i].run)g_mquery[i].run->error=MQ_LOST;
    }
    pthread_mutex_unlock(&g_qlock);
}
/* Called while the frame belongs exclusively to the encoder. Detach the
 * references before the recording buffers become reusable. */
static MQSubmission *mq_capture(int b){
    if(b<0)return NULL;pthread_mutex_lock(&g_qlock);MQFrame*f=&g_mqframe[b];
    MQSubmission*s=f->count?calloc(1,sizeof *s+g_dn[b]*sizeof(uint64_t)):NULL;
    if(s){s->frame=*f;s->draws=g_dn[b];for(unsigned i=0;i<s->draws;i++)s->masks[i]=g_dbuf[b][i].query_mask;
        for(unsigned i=0;i<f->count;i++)f->run[i]->queued--;
    }else for(unsigned i=0;i<f->count;i++){MQRun*r=f->run[i];r->error=MQ_OOM;r->queued--;r->pending--;mq_release(r);}
    memset(f,0,sizeof *f);pthread_mutex_unlock(&g_qlock);return s;
}
static void mq_complete(MQSubmission*s,const uint64_t *samples,int success){
    if(!s)return;pthread_mutex_lock(&g_qlock);
    for(unsigned j=0;j<s->frame.count;j++){MQRun*r=s->frame.run[j];
        if(!success || s->failed)r->error=MQ_LOST;
        else for(unsigned i=0;i<s->draws;i++)if(s->masks[i]&(1ull<<j))r->samples+=samples[i];
        r->pending--;mq_release(r);
    }
    pthread_mutex_unlock(&g_qlock);free(s);
}
static id<MTLBuffer> mq_buffer(MQSubmission*s){
    if(!s)return nil;id<MTLBuffer>b=[g_dev newBufferWithLength:MAX(8,s->draws*8) options:MTLResourceStorageModeShared];
    if(b)memset(b.contents,0,b.length);return b;
}
static void mq_encode(id<MTLRenderCommandEncoder>encoder,id<MTLBuffer>buffer,const MDraw *draw,unsigned index){
    if(buffer)[encoder setVisibilityResultMode:draw->query_mask?MTLVisibilityResultModeCounting:MTLVisibilityResultModeDisabled offset:draw->query_mask?index*8:0];
}

static void mq_fail_active(void){for(MQRun*r=g_mqactive;r;r=r->next)r->error=MQ_OOM;}
static int mq_frame_pending(int b){return b>=0 && g_mqframe[b].count!=0;}
