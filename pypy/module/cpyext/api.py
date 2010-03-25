import ctypes
import sys

import py

from pypy.translator.goal import autopath
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.rpython.tool import rffi_platform
from pypy.rpython.lltypesystem import ll2ctypes
from pypy.rpython.annlowlevel import llhelper
from pypy.translator.c.database import LowLevelDatabase
from pypy.translator.tool.cbuild import ExternalCompilationInfo
from pypy.tool.udir import udir
from pypy.translator import platform
from pypy.module.cpyext.state import State
from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.interpreter.baseobjspace import W_Root
from pypy.interpreter.gateway import ObjSpace, unwrap_spec
from pypy.objspace.std.stringobject import W_StringObject
# CPython 2.4 compatibility
from py.builtin import BaseException


Py_ssize_t = lltype.Signed

include_dir = py.path.local(autopath.pypydir) / 'module' / 'cpyext' / 'include'
include_dirs = [
    include_dir,
    udir,
    ]

class CConfig:
    _compilation_info_ = ExternalCompilationInfo(
        include_dirs=include_dirs,
        includes=['Python.h']
        )

class CConfig_constants:
    _compilation_info_ = CConfig._compilation_info_

constant_names = """
Py_TPFLAGS_READY Py_TPFLAGS_READYING
METH_COEXIST METH_STATIC METH_CLASS METH_NOARGS
Py_TPFLAGS_HEAPTYPE
""".split()
for name in constant_names:
    setattr(CConfig_constants, name, rffi_platform.ConstantInteger(name))
udir.join('pypy_decl.h').write("/* Will be filled later */")
globals().update(rffi_platform.configure(CConfig_constants))

_NOT_SPECIFIED = object()
CANNOT_FAIL = object()

# The same function can be called in three different contexts:
# (1) from C code
# (2) in the test suite, though the "api" object
# (3) from RPython code, for example in the implementation of another function.
#
# In contexts (2) and (3), a function declaring a PyObject argument type will
# receive a wrapped pypy object if the parameter name starts with 'w_', a
# reference (= rffi pointer) otherwise; conversion is automatic.  Context (2)
# only allows calls with a wrapped object.
#
# Functions with a PyObject return type should return a wrapped object.
#
# Functions may raise exceptions.  In context (3), the exception flows normally
# through the calling function.  In context (1) and (2), the exception is
# caught; if it is an OperationError, it is stored in the thread state; other
# exceptions generate a OperationError(w_SystemError).  In every case the
# funtion returns the error value specifed in the API.
#

class ApiFunction:
    def __init__(self, argtypes, restype, callable, borrowed, error):
        self.argtypes = argtypes
        self.restype = restype
        self.functype = lltype.Ptr(lltype.FuncType(argtypes, restype))
        self.callable = callable
        self.borrowed = borrowed
        if error is not _NOT_SPECIFIED:
            self.error_value = error

        # extract the signature from the (CPython-level) code object
        from pypy.interpreter import pycode
        argnames, varargname, kwargname = pycode.cpython_code_signature(callable.func_code)

        assert argnames[0] == 'space'
        self.argnames = argnames[1:]
        assert len(self.argnames) == len(self.argtypes)

    def get_llhelper(self, space):
        llh = getattr(self, '_llhelper', None)
        if llh is None:
            llh = llhelper(self.functype, make_wrapper(space, self.callable))
            self._llhelper = llh
        return llh

def cpython_api(argtypes, restype, borrowed=False, error=_NOT_SPECIFIED, external=True):
    if error is _NOT_SPECIFIED:
        if restype is PyObject:
            error = lltype.nullptr(PyObject.TO)
        elif restype is lltype.Void:
            error = CANNOT_FAIL

    def decorate(func):
        api_function = ApiFunction(argtypes, restype, func, borrowed, error)

        if error is _NOT_SPECIFIED:
            raise ValueError("function %s has no return value for exceptions"
                             % func)
        def unwrapper(space, *args):
            "NOT_RPYTHON: XXX unsure"
            newargs = []
            to_decref = []
            for i, arg in enumerate(args):
                if api_function.argtypes[i] is PyObject:
                    if (isinstance(arg, W_Root) and
                        not api_function.argnames[i].startswith('w_')):
                        arg = make_ref(space, arg)
                        to_decref.append(arg)
                    elif (not isinstance(arg, W_Root) and
                          api_function.argnames[i].startswith('w_')):
                        arg = from_ref(space, arg)
                newargs.append(arg)
            try:
                try:
                    return func(space, *newargs)
                except OperationError, e:
                    if not hasattr(api_function, "error_value"):
                        raise
                    state = space.fromcache(State)
                    e.normalize_exception(space)
                    state.exc_type = e.w_type
                    state.exc_value = e.get_w_value(space)
                    return api_function.error_value
            finally:
                from pypy.module.cpyext.macros import Py_DECREF
                for arg in to_decref:
                    Py_DECREF(space, arg)

        func.api_func = api_function
        unwrapper.api_func = api_function
        unwrapper.func = func
        if external:
            FUNCTIONS[func.func_name] = api_function
        INTERPLEVEL_API[func.func_name] = unwrapper
        return unwrapper
    return decorate

def cpython_api_c():
    def decorate(func):
        FUNCTIONS_C[func.func_name] = None
    return decorate

def cpython_struct(name, fields, forward=None):
    configname = name.replace(' ', '__')
    setattr(CConfig, configname, rffi_platform.Struct(name, fields))
    if forward is None:
        forward = lltype.ForwardReference()
    TYPES[configname] = forward
    return forward

INTERPLEVEL_API = {}
FUNCTIONS = {}
FUNCTIONS_C = {}
TYPES = {}
GLOBALS = {
    'Py_None': ('PyObject*', 'space.w_None'),
    'Py_True': ('PyObject*', 'space.w_True'),
    'Py_False': ('PyObject*', 'space.w_False'),
    'PyExc_Exception': ('PyObject*', 'space.w_Exception'),
    'PyExc_TypeError': ('PyObject*', 'space.w_TypeError'),
    'PyType_Type#': ('PyTypeObject*', 'space.w_type'),
    'PyBaseObject_Type#': ('PyTypeObject*', 'space.w_object'),
    }

# It is important that these PyObjects are allocated in a raw fashion
# Thus we cannot save a forward pointer to the wrapped object
# So we need a forward and backward mapping in our State instance
PyObjectStruct = lltype.ForwardReference()
PyObject = lltype.Ptr(PyObjectStruct)
PyObjectFields = (("obj_refcnt", lltype.Signed), ("obj_type", PyObject))
PyVarObjectFields = PyObjectFields + (("obj_size", Py_ssize_t), )
cpython_struct('struct _object', PyObjectFields, PyObjectStruct)

PyStringObject = lltype.ForwardReference()
PyStringObjectPtr = lltype.Ptr(PyStringObject)
PyStringObjectFields = PyVarObjectFields + \
    (("buffer", rffi.CCHARP), ("size", Py_ssize_t))
cpython_struct("PyStringObject", PyStringObjectFields, PyStringObject)

def configure():
    for name, TYPE in rffi_platform.configure(CConfig).iteritems():
        if name in TYPES:
            TYPES[name].become(TYPE)

class NullPointerException(Exception):
    pass

class InvalidPointerException(Exception):
    pass

def get_padded_type(T, size):
    fields = T._flds.copy()
    hints = T._hints.copy()
    hints["size"] = size
    del hints["fieldoffsets"]
    pad_fields = []
    new_fields = []
    for name in T._names:
        new_fields.append((name, fields[name]))
    for i in xrange(size - rffi.sizeof(T)):
        new_fields.append(("custom%i" % (i, ), lltype.Char))
    hints["padding"] = hints["padding"] + tuple(pad_fields)
    return lltype.Struct(hints["c_name"], hints=hints, *new_fields)

def make_ref(space, w_obj, borrowed=False, steal=False):
    if w_obj is None:
        return lltype.nullptr(PyObject.TO)
    assert isinstance(w_obj, W_Root)
    state = space.fromcache(State)
    py_obj = state.py_objects_w2r.get(w_obj)
    if py_obj is None:
        from pypy.module.cpyext.typeobject import allocate_type_obj,\
                W_PyCTypeObject, W_PyCObject
        w_type = space.type(w_obj)
        if space.is_w(w_type, space.w_type):
            py_obj = allocate_type_obj(space, w_obj)
            if space.is_w(w_type, w_obj):
                pto = py_obj
            else:
                pto = make_ref(space, w_type)
        elif isinstance(w_obj, W_PyCObject):
            w_type = space.type(w_obj)
            assert isinstance(w_type, W_PyCTypeObject)
            pto = w_type.pto
            basicsize = pto._obj.c_tp_basicsize
            T = get_padded_type(PyObject.TO, basicsize)
            py_obj = lltype.malloc(T, None, flavor="raw")
        elif isinstance(w_obj, W_StringObject):
            py_obj = lltype.malloc(PyStringObjectPtr.TO, None, flavor='raw')
            py_obj.c_size = len(space.str_w(w_obj))
            py_obj.c_buffer = lltype.nullptr(rffi.CCHARP.TO)
            pto = make_ref(space, space.w_str)
            py_obj = rffi.cast(PyObject, py_obj)
        else:
            py_obj = lltype.malloc(PyObject.TO, None, flavor="raw")
            pto = make_ref(space, space.type(w_obj))
        py_obj.c_obj_type = rffi.cast(PyObject, pto)
        py_obj.c_obj_refcnt = 1
        ctypes_obj = ll2ctypes.lltype2ctypes(py_obj)
        ptr = ctypes.cast(ctypes_obj, ctypes.c_void_p).value
        py_obj = ll2ctypes.ctypes2lltype(PyObject, ctypes_obj)
        py_obj = rffi.cast(PyObject, py_obj)
        state.py_objects_w2r[w_obj] = py_obj
        state.py_objects_r2w[ptr] = w_obj
    elif not steal:
        py_obj.c_obj_refcnt += 1
    # XXX borrowed references?
    return py_obj

def force_string(space, ref):
    state = space.fromcache(State)
    ref = rffi.cast(PyStringObjectPtr, ref)
    s = rffi.charpsize2str(ref.c_buffer, ref.c_size)
    ref = rffi.cast(PyObject, ref)
    w_str = space.wrap(s)
    state.py_objects_w2r[w_str] = ref
    ctypes_obj = ll2ctypes.lltype2ctypes(ref)
    ptr = ctypes.cast(ctypes_obj, ctypes.c_void_p).value
    state.py_objects_r2w[ptr] = w_str
    return w_str


def from_ref(space, ref):
    if not ref:
        return None
    state = space.fromcache(State)
    ptr = ctypes.addressof(ref._obj._storage)
    try:
        obj = state.py_objects_r2w[ptr]
    except KeyError:
        if from_ref(space, ref.c_obj_type) is space.w_str:
            return force_string(space, ref)
        else:
            raise InvalidPointerException("Got invalid reference to a PyObject: %r" % (ref, ))
    return obj

def clear_memory(space):
    from pypy.module.cpyext.macros import Py_DECREF
    state = space.fromcache(State)
    while state.py_objects_r2w:
        key = state.py_objects_r2w.keys()[0]
        Py_DECREF(space, key)
    state.reset()


def general_check(space, w_obj, w_type):
    w_obj_type = space.type(w_obj)
    return int(space.is_w(w_obj_type, w_type) or space.is_true(space.issubtype(w_obj_type, w_type)))

def make_wrapper(space, callable):
    def wrapper(*args):
        boxed_args = []
        # XXX use unrolling_iterable here
        print >>sys.stderr, callable,
        for i, typ in enumerate(callable.api_func.argtypes):
            arg = args[i]
            if (typ is PyObject and
                callable.api_func.argnames[i].startswith('w_')):
                if arg:
                    arg = from_ref(space, arg)
                else:
                    arg = None
            boxed_args.append(arg)
        state = space.fromcache(State)
        try:
            retval = callable(space, *boxed_args)
            print >>sys.stderr, " DONE"
        except OperationError, e:
            failed = True
            e.normalize_exception(space)
            state.exc_type = e.w_type
            state.exc_value = e.get_w_value(space)
        except BaseException, e:
            failed = True
            state.exc_type = space.w_SystemError
            state.exc_value = space.wrap(str(e))
            import traceback
            traceback.print_exc()
        else:
            failed = False

        if failed:
            error_value = callable.api_func.error_value
            if error_value is CANNOT_FAIL:
                raise SystemError("The function %r was not supposed to fail"
                                  % (callable,))
            return error_value

        if callable.api_func.restype is PyObject:
            retval = make_ref(space, retval, borrowed=callable.api_func.borrowed)
        if callable.api_func.restype is rffi.INT_real:
            retval = rffi.cast(rffi.INT_real, retval)
        return retval
    return wrapper

#_____________________________________________________
# Build the bridge DLL, Allow extension DLLs to call
# back into Pypy space functions
# Do not call this more than once per process
def build_bridge(space, rename=True):
    db = LowLevelDatabase()

    export_symbols = list(FUNCTIONS) + list(FUNCTIONS_C) + list(GLOBALS)

    structindex = {}

    prologue = """\
    #include <pypy_rename.h>
    #include <Python.h>
    """
    pypy_rename = []
    renamed_symbols = []
    if rename:
        for name in export_symbols:
            if name.startswith("PyPy"):
                renamed_symbols.append(name)
                continue
            if "#" in name:
                deref = "*"
            else:
                deref = ""
            name = name.replace("#", "")
            newname = name.replace('Py', 'PyPy')
            pypy_rename.append('#define %s %s%s' % (name, deref, newname))
            renamed_symbols.append(newname)
    export_symbols = renamed_symbols
    pypy_rename_h = udir.join('pypy_rename.h')
    pypy_rename_h.write('\n'.join(pypy_rename))


    configure() # needs pypy_rename.h

    # Structure declaration code
    members = []
    for name, func in FUNCTIONS.iteritems():
        cdecl = db.gettype(func.functype)
        members.append(cdecl.replace('@', name) + ';')
        structindex[name] = len(structindex)
    structmembers = '\n'.join(members)
    struct_declaration_code = """\
    struct PyPyAPI {
    %(members)s
    } _pypyAPI;
    struct PyPyAPI* pypyAPI = &_pypyAPI;
    """ % dict(members=structmembers)

    # implement function callbacks and generate function decls
    functions = []
    pypy_decls = []
    for name, func in sorted(FUNCTIONS.iteritems()):
        restype = db.gettype(func.restype).replace('@', '')
        args = []
        for i, argtype in enumerate(func.argtypes):
            arg = db.gettype(argtype)
            arg = arg.replace('@', 'arg%d' % (i,))
            args.append(arg)
        args = ', '.join(args)
        callargs = ', '.join('arg%d' % (i,) for i in range(len(func.argtypes)))
        header = "%s %s(%s)" % (restype, name, args)
        pypy_decls.append(header + ";")
        body = "{ return _pypyAPI.%s(%s); }" % (name, callargs)
        functions.append('%s\n%s\n' % (header, body))

    pypy_decl_h = udir.join('pypy_decl.h')
    pypy_decl_h.write('\n'.join(pypy_decls))

    global_objects = []
    for name, (type, expr) in GLOBALS.iteritems():
        global_objects.append('%s %s = NULL;' % (type, name.replace("#", "")))
    global_code = '\n'.join(global_objects)
    code = (prologue +
            struct_declaration_code +
            global_code +
            '\n' +
            '\n'.join(functions))

    # Build code and get pointer to the structure
    eci = ExternalCompilationInfo(
        include_dirs=include_dirs,
        separate_module_sources=[code],
        separate_module_files=[include_dir / "typeobject.c",
                               include_dir / "varargwrapper.c"],
        export_symbols=['pypyAPI'] + export_symbols,
        )
    eci = eci.convert_sources_to_files()
    modulename = platform.platform.compile(
        [], eci,
        outputfilename=str(udir / "module_cache" / "pypyapi"),
        standalone=False)

    # load the bridge, and init structure
    import ctypes
    bridge = ctypes.CDLL(str(modulename))
    pypyAPI = ctypes.POINTER(ctypes.c_void_p).in_dll(bridge, 'pypyAPI')

    # populate static data
    for name, (type, expr) in GLOBALS.iteritems():
        name = name.replace("#", "")
        if rename:
            name = name.replace('Py', 'PyPy')
        w_obj = eval(expr)
        ptr = ctypes.c_void_p.in_dll(bridge, name)
        ptr.value = ctypes.cast(ll2ctypes.lltype2ctypes(make_ref(space, w_obj)),
            ctypes.c_void_p).value
        # hack, init base of the type type
        if name == "PyType_Type":
            pto = rffi.cast(PyTypeObjectPtr, ptr)
            pto.c_tp_base = make_ref(space, w_object)

    # implement structure initialization code
    for name, func in FUNCTIONS.iteritems():
        pypyAPI[structindex[name]] = ctypes.cast(
            ll2ctypes.lltype2ctypes(func.get_llhelper(space)),
            ctypes.c_void_p)

    return modulename.new(ext='')

@unwrap_spec(ObjSpace, str, str)
def load_extension_module(space, path, name):
    state = space.fromcache(State)
    from pypy.rlib import libffi
    try:
        dll = libffi.CDLL(path)
    except libffi.DLOpenError, e:
        raise operationerrfmt(
            space.w_ImportError,
            "unable to load extension module '%s': %s",
            path, e.msg)
    try:
        initfunc = dll.getpointer(
            'init%s' % (name,), [], libffi.ffi_type_void)
    except KeyError:
        raise operationerrfmt(
            space.w_ImportError,
            "function init%s not found in library %s",
            name, path)
    dll.unload_on_finalization = False
    initfunc.call(lltype.Void)
    state.check_and_raise_exception()

def generic_cpy_call(space, func, *args, **kwargs):
    from pypy.module.cpyext.macros import Py_DECREF
    from pypy.module.cpyext.pyerrors import PyErr_Occurred

    decref_args = kwargs.pop("decref_args", True)
    assert not kwargs
    boxed_args = []
    for arg in args: # XXX ur needed
        if isinstance(arg, W_Root) or arg is None:
            boxed_args.append(make_ref(space, arg))
        else:
            boxed_args.append(arg)
    result = func(*boxed_args)
    try:
        FT = lltype.typeOf(func).TO
        if FT.RESULT is PyObject:
            ret = from_ref(space, result)

            # Check for exception consistency
            has_error = PyErr_Occurred(space) is not None
            has_result = ret is not None
            if has_error and has_result:
                raise OperationError(space.w_SystemError, space.wrap(
                    "An exception was set, but function returned a value"))
            elif not has_error and not has_result:
                raise OperationError(space.w_SystemError, space.wrap(
                    "Function returned a NULL result without setting an exception"))

            if has_error:
                state = space.fromcache(State)
                state.check_and_raise_exception()

            Py_DECREF(space, ret) # XXX WHY??
            return ret
    finally:
        if decref_args:
            for arg in args: # XXX ur needed
                if arg is not None and isinstance(arg, W_Root):
                    Py_DECREF(space, arg)

