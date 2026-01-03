#include <init.h>
#include <types.h>
#include <macros.h>

static int fragmentID = -2;

#ifdef __cplusplus
extern "C" {
#endif

void __init_cpp_exceptions(void);
void __fini_cpp_exceptions(void);
void __destroy_global_chain(void);

#ifdef __cplusplus
}
#endif

inline static char* GetR2() {
    register char* ret;
    asm {
        mr ret, r2;
    }
    return ret;
}

void __init_cpp_exceptions(void) {
    if (fragmentID == -2) {
        fragmentID = __register_fragment(&_eti_init_info, GetR2());
    }
}

void __fini_cpp_exceptions(void) {
    if (fragmentID != -2) {
        __unregister_fragment(fragmentID);
        fragmentID = -2;
    }
}

DECL_SECTION(".ctors")
funcptr_t __init_cpp_exceptions_reference = __init_cpp_exceptions;

DECL_SECTION(".dtors")
funcptr_t __destroy_global_chain_reference = __destroy_global_chain;
DECL_SECTION(".dtors")
funcptr_t __fini_cpp_exceptions_reference = __fini_cpp_exceptions;
