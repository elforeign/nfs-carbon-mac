// The catalogue (game_pipeline_recipes.h) is built on the four shader build queues after shader publication,
// as in Most Wanted's pipeline_prewarm; frames never join these jobs, and a miss still builds on demand.
void pipeline_prewarm(dispatch_queue_t __strong queues[4], NSUInteger scene_samples) {
    scene_sample_count=scene_samples;
    if(enabled()) {
        NSMutableSet<NSData *> *scheduled=[NSMutableSet new];
        for(size_t i=0;i<sizeof recipes/sizeof *recipes;++i) {
            PipelineRecipe r=resolve_recipe(recipes[i]);
            extern uint64_t carbon_coat_recipe_key(uint64_t);
            r.vertex=carbon_coat_recipe_key(r.vertex);
            r.fragment=carbon_coat_recipe_key(r.fragment);
            NSData *key=[NSData dataWithBytes:&r length:sizeof r];
            if([scheduled containsObject:key])continue;
            [scheduled addObject:key];
            dispatch_async(queues[i%4], ^{ @autoreleasepool {
                MTLRenderPipelineDescriptor *d=descriptor(&r);
                if(!d) { if(diag_on)diag_event("pipeline_prewarm: missing_shader=%zu",i); return; }
                NSError *error=nil;
                if(!pipeline_cached(d,r.vertex,r.fragment,"prewarm",&error) && diag_on)
                    diag_event("pipeline_prewarm: failed=%zu %s",i,error.localizedDescription.UTF8String);
            }});
        }
    }
#include "game_hdr_prewarm.h"
}
