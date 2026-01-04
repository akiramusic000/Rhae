#ifndef NMWEXCEPTION_H
#define NMWEXCEPTION_H

#include <types.h>
#include <revolution/OS.h>
#include <runtime/Gecko_ExceptionPPC.h>

#ifdef __cplusplus
extern "C" {
#endif

void* __construct_new_array(void*, funcptr_t, funcptr_t, size_t, size_t);
void __construct_array(void*, funcptr_t, funcptr_t, size_t, size_t);
void __destroy_arr(void*, funcptr_t, size_t, size_t);
void __destroy_new_array(void*, funcptr_t);

#ifdef __cplusplus
};
#endif

#endif
