#ifndef Py_PYTHON_H
#define Py_PYTHON_H

// XXX this should be in pyconfig.h

#define HAVE_LONG_LONG 1
#define HAVE_STDARG_PROTOTYPES 1
#define PY_FORMAT_LONG_LONG "ll"
#define PY_LONG_LONG long long
#define SIZEOF_LONG_LONG sizeof(PY_LONG_LONG)
#define PY_FORMAT_SIZE_T "z"

/* Compat stuff */
#ifndef _WIN32
# include <inttypes.h>
# include <stdint.h>
# include <stddef.h>
# define Py_DEPRECATED(VERSION_UNUSED) __attribute__((__deprecated__))
# define PyAPI_DATA(RTYPE) extern RTYPE
#else
# define Py_DEPRECATED(VERSION_UNUSED)
# ifdef Py_BUILD_CORE
#  define PyAPI_DATA(RTYPE) extern __declspec(dllexport) RTYPE
# else
#  define PyAPI_DATA(RTYPE) extern __declspec(dllimport) RTYPE
# endif
#endif
#define Py_ssize_t long

/* Convert a possibly signed character to a nonnegative int */
/* XXX This assumes characters are 8 bits wide */
#ifdef __CHAR_UNSIGNED__
#define Py_CHARMASK(c)		(c)
#else
#define Py_CHARMASK(c)		((unsigned char)((c) & 0xff))
#endif

#define Py_MEMCPY memcpy

#include <pypy_macros.h>

#include "patchlevel.h"

#include "object.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <locale.h>
#include <ctype.h>

#include "boolobject.h"
#include "floatobject.h"
#include "methodobject.h"

#include "modsupport.h"
#include "pythonrun.h"
#include "pyerrors.h"
#include "stringobject.h"
#include "descrobject.h"
#include "tupleobject.h"
#include "dictobject.h"
#include "intobject.h"
#include "eval.h"

// XXX This shouldn't be included here
#include "structmember.h"

#include <pypy_decl.h>

#endif
