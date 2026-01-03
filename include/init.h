#ifndef INIT_H
#define INIT_H

typedef struct _eti_init_info_t {
    void* eti_start;
    void* eti_end;
    void* code_start;
    unsigned long code_size;
} _eti_init_info_t;

extern _eti_init_info_t _eti_init_info;

#ifdef __cplusplus
extern "C" {
#endif

extern int __register_fragment(_eti_init_info_t*, char*);
extern void __unregister_fragment(int);

#ifdef __cplusplus
}
#endif

#endif
