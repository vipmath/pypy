import pypy.interpreter.appfile
from pypy.interpreter.baseobjspace import *
from multimethod import *

if not isinstance(bool, type):
    booltype = ()
else:
    booltype = bool


class W_Object:
    "Parent base class for wrapped objects."
    delegate_once = {}
    statictype = None
    
    def __init__(w_self, space):
        w_self.space = space

    def get_builtin_impl_class(w_self):
        return w_self.__class__

W_ANY = W_Object  # synonyms for use in .register()
MultiMethod.ASSERT_BASE_TYPE = W_Object


def registerimplementation(implcls):
    # this function should ultimately register the implementation class somewhere
    # right now its only purpose is to make sure there is a
    # delegate_once attribute.
    implcls.__dict__.setdefault("delegate_once", {})


##################################################################

class StdObjSpace(ObjSpace):
    """The standard object space, implementing a general-purpose object
    library in Restricted Python."""

    PACKAGE_PATH = 'objspace.std'

    class AppFile(pypy.interpreter.appfile.AppFile):
        pass
    AppFile.LOCAL_PATH = [PACKAGE_PATH]


    def standard_types(self):
        class result:
            "Import here the types you want to have appear in __builtin__."

            from objecttype import W_ObjectType
            from booltype   import W_BoolType
            from inttype    import W_IntType
            from floattype  import W_FloatType
            from tupletype  import W_TupleType
            from listtype   import W_ListType
            from dicttype   import W_DictType
            from stringtype import W_StringType
            from typetype   import W_TypeType
            from slicetype  import W_SliceType
        return [value for key, value in result.__dict__.items()
                      if not key.startswith('_')]   # don't look

    def clone_exception_heirachy(self):
	import exceptions
        from usertype import W_UserType
        self.w_Exception = W_UserType(self, 
                                      self.wrap("Exception"),
                                      self.newtuple([]),
                                      self.newdict([]))
        done = {'Exception': self.w_Exception}
        self.w_IndexError = self.w_Exception
        for k in dir(exceptions):
            v = getattr(exceptions, k)
            if isinstance(v, str):
                continue
            stack = [k]
            while stack:
                next = stack[-1]
                nextv = getattr(exceptions, next)
                if next in done:
                    stack.pop()
                else:
                    nb = nextv.__bases__[0]
                    w_nb = done.get(nb.__name__)
                    if w_nb is None:
                        stack.append(nb.__name__)
                    else:
                        w_exc = self.call_function(
                            self.w_type,
                            self.wrap(next),
                            self.newtuple([w_nb]),
                            self.newdict([]))
                        setattr(self, 'w_' + next, w_exc)
                        done[next] = w_exc
                        stack.pop()
        return done
            
    def initialize(self):
        from noneobject    import W_NoneObject
        from boolobject    import W_BoolObject
        from cpythonobject import W_CPythonObject
        self.w_None  = W_NoneObject(self)
        self.w_False = W_BoolObject(self, False)
        self.w_True  = W_BoolObject(self, True)
        self.w_NotImplemented = self.wrap(NotImplemented)  # XXX do me
        # hack in the exception classes
        import __builtin__, types
        newstuff = {"False": self.w_False,
                    "True" : self.w_True,
                    "None" : self.w_None,
                    "NotImplemented": self.w_NotImplemented,
                    }
#         for n, c in __builtin__.__dict__.iteritems():
#             if isinstance(c, types.ClassType) and issubclass(c, Exception):
#                 w_c = W_CPythonObject(self, c)
#                 setattr(self, 'w_' + c.__name__, w_c)
#                 newstuff[c.__name__] = w_c
        # make the types
        self.types_w = {}
        for typeclass in self.standard_types():
            w_type = self.get_typeinstance(typeclass)
            setattr(self, 'w_' + typeclass.typename, w_type)
            newstuff[typeclass.typename] = w_type
        newstuff.update(self.clone_exception_heirachy())
        self.make_builtins()
        self.make_sys()
        # insert these into the newly-made builtins
        for key, w_value in newstuff.items():
            self.setitem(self.w_builtins, self.wrap(key), w_value)
        # add a dummy __import__  XXX fixme
#        w_import = self.wrap(__import__)
#        self.setitem(self.w_builtins, self.wrap("__import__"), w_import)

    def get_typeinstance(self, typeclass):
        assert typeclass.typename is not None, (
            "get_typeinstance() cannot be used for %r" % typeclass)
        # types_w maps each W_XxxType class to its unique-for-this-space instance
        try:
            w_type = self.types_w[typeclass]
        except:
            w_type = self.types_w[typeclass] = typeclass(self)
        return w_type

    def wrap(self, x):
        "Wraps the Python value 'x' into one of the wrapper classes."
        if x is None:
            return self.w_None
        if isinstance(x, W_Object):
            raise TypeError, "attempt to wrap already wrapped object: %s"%(x,)
        if isinstance(x, int):
            if isinstance(x, booltype):
                return self.newbool(x)
            import intobject
            return intobject.W_IntObject(self, x)
        if isinstance(x, str):
            import stringobject
            return stringobject.W_StringObject(self, x)
        if isinstance(x, dict):
            items_w = [(self.wrap(k), self.wrap(v)) for (k, v) in x.iteritems()]
            import dictobject
            return dictobject.W_DictObject(self, items_w)
        if isinstance(x, float):
            import floatobject
            return floatobject.W_FloatObject(self, x)
        if isinstance(x, tuple):
            wrappeditems = [self.wrap(item) for item in x]
            import tupleobject
            return tupleobject.W_TupleObject(self, wrappeditems)
        if isinstance(x, list):
            wrappeditems = [self.wrap(item) for item in x]
            import listobject
            return listobject.W_ListObject(self, wrappeditems)
        import cpythonobject
        return cpythonobject.W_CPythonObject(self, x)

    def newtuple(self, list_w):
        import tupleobject
        return tupleobject.W_TupleObject(self, list_w)

    def newlist(self, list_w):
        import listobject
        return listobject.W_ListObject(self, list_w)

    def newdict(self, list_pairs_w):
        import dictobject
        return dictobject.W_DictObject(self, list_pairs_w)

    def newslice(self, w_start, w_end, w_step):
        # w_step may be a real None
        import sliceobject
        return sliceobject.W_SliceObject(self, w_start, w_end, w_step)

    def newfunction(self, code, w_globals, w_defaultarguments, w_closure=None):
        import funcobject
        return funcobject.W_FuncObject(self, code, w_globals,
                                       w_defaultarguments, w_closure)

    def newmodule(self, w_name):
        import moduleobject
        return moduleobject.W_ModuleObject(self, w_name)

    def newstring(self, chars_w):
        try:
            chars = [chr(self.unwrap(w_c)) for w_c in chars_w]
        except TypeError:   # chr(not-an-integer)
            raise OperationError(self.w_TypeError,
                                 self.wrap("an integer is required"))
        except ValueError:  # chr(out-of-range)
            raise OperationError(self.w_ValueError,
                                 self.wrap("character code not in range(256)"))
        import stringobject
        return stringobject.W_StringObject(self, ''.join(chars))

    # special multimethods
    unwrap  = MultiMethod('unwrap', 1, [])   # returns an unwrapped object
    is_true = MultiMethod('nonzero', 1, [])  # returns an unwrapped bool
    # XXX do something about __nonzero__ !

    getdict = MultiMethod('getdict', 1, [])  # get '.__dict__' attribute


# add all regular multimethods to StdObjSpace
for _name, _symbol, _arity, _specialnames in ObjSpace.MethodTable:
    setattr(StdObjSpace, _name, MultiMethod(_symbol, _arity, _specialnames))

# import the common base W_ObjectObject as well as
# default implementations of some multimethods for all objects
# that don't explicitely override them or that raise FailedToImplement
import pypy.objspace.std.objectobject
import pypy.objspace.std.default
