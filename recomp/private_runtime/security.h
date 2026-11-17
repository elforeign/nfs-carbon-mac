/* Minimal process-token SID queries and ephemeral CryptoAPI RNG providers.
 * No key containers, impersonation or Windows credentials are fabricated. */
static uint32_t private_sids[64];
static unsigned char private_rng_providers[64];
static int private_security(Cpu*c,const char*fn){
    if(IS("CryptAcquireContextA")){
        uint32_t out=arg(c,0),flags=arg(c,4);if(!out){last_error=87;RET(0,5);}M32(out)=0;
        if(arg(c,1)||(flags&0xf0000000u)!=0xf0000000u||(flags&0x0fffffbfu)){last_error=0x80090016u;RET(0,5);}
        if(arg(c,3)!=1&&arg(c,3)!=24){last_error=0x80090014u;RET(0,5);}
        for(unsigned i=0;i<64;i++)if(!private_rng_providers[i]){private_rng_providers[i]=1;M32(out)=0xf4000000u+4*i;RET(1,5);}last_error=8;RET(0,5);
    }
    if(IS("CryptGenRandom")||IS("CryptReleaseContext")){
        uint32_t h=arg(c,0),i=(h-0xf4000000u)/4;int random=IS("CryptGenRandom");
        if(h<0xf4000000u||(h&3)||i>=64||!private_rng_providers[i]){last_error=6;RET(0,random?3:2);}
        if(random){uint32_t p=arg(c,2),n=arg(c,1);if((n&&!p)||(uint64_t)p+n>0x100000000ull){last_error=87;RET(0,3);}arc4random_buf(G+p,n);RET(1,3);}
        if(arg(c,1)){last_error=87;RET(0,2);}private_rng_providers[i]=0;RET(1,2);
    }
    if(IS("AllocateAndInitializeSid")){
        uint32_t authority=arg(c,0),n=arg(c,1),out=arg(c,10);if(!out){last_error=87;RET(0,11);}M32(out)=0;
        if(!authority||n>8){last_error=87;RET(0,11);}unsigned i;for(i=0;i<64&&private_sids[i];i++);if(i==64){last_error=8;RET(0,11);}
        uint32_t p=gmalloc(8+4*n);if(!p){last_error=8;RET(0,11);}M8(p)=1;M8(p+1)=n;memcpy(G+p+2,G+authority,6);for(unsigned k=0;k<n;k++)M32(p+8+4*k)=arg(c,2+k);private_sids[i]=p;M32(out)=p;RET(1,11);
    }
    if(IS("FreeSid")){uint32_t p=arg(c,0);for(unsigned i=0;i<64;i++)if(p&&private_sids[i]==p){gfree(p);private_sids[i]=0;RET(0,1);}last_error=87;RET(p,1);}
    if(IS("CheckTokenMembership")){
        uint32_t p=arg(c,1),out=arg(c,2);if(!out){last_error=87;RET(0,3);}M32(out)=0;if(arg(c,0)){last_error=6;RET(0,3);}
        if(!p||M8(p)!=1||M8(p+1)>8){last_error=1337;RET(0,3);}uint64_t authority=0;for(unsigned i=0;i<6;i++)authority=(authority<<8)|M8(p+2+i);unsigned n=M8(p+1);
        if(n==1&&((authority==1&&M32(p+8)==0)||(authority==5&&M32(p+8)==11)))M32(out)=1;
        if(authority==5&&n==2&&M32(p+8)==32&&(M32(p+12)==545||(M32(p+12)==544&&geteuid()==0)))M32(out)=1;
        RET(1,3);
    }return 0;
}
