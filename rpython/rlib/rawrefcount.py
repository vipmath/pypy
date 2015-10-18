#
#  See documentation in pypy/doc/discussion/rawrefcount.rst
#
import sys, weakref
from rpython.rtyper.lltypesystem import lltype, llmemory
from rpython.rlib.objectmodel import we_are_translated, specialize
from rpython.rtyper.extregistry import ExtRegistryEntry
from rpython.rlib import rgc


REFCNT_FROM_PYPY       = 80
REFCNT_FROM_PYPY_LIGHT = REFCNT_FROM_PYPY + (sys.maxint//2+1)

RAWREFCOUNT_DEALLOC = lltype.Ptr(lltype.FuncType([llmemory.Address],
                                                 lltype.Void))


def _build_pypy_link(p):
    res = len(_adr2pypy)
    _adr2pypy.append(p)
    return res


def init(dealloc_callback=None):
    "NOT_RPYTHON: set up rawrefcount with the GC"
    global _p_list, _o_list, _adr2pypy, _pypy2ob, _dealloc_callback
    _p_list = []
    _o_list = []
    _adr2pypy = [None]
    _pypy2ob = {}
    _dealloc_callback = dealloc_callback

def create_link_pypy(p, ob):
    "NOT_RPYTHON: a link where the PyPy object contains some or all the data"
    assert p not in _pypy2ob
    assert not ob.c_ob_pypy_link
    ob.c_ob_pypy_link = _build_pypy_link(p)
    _pypy2ob[p] = ob
    _p_list.append(ob)

def create_link_pyobj(p, ob):
    """NOT_RPYTHON: a link where the PyObject contains all the data.
       from_obj() will not work on this 'p'."""
    assert p not in _pypy2ob
    assert not ob.c_ob_pypy_link
    ob.c_ob_pypy_link = _build_pypy_link(p)
    _o_list.append(ob)

def from_obj(OB_PTR_TYPE, p):
    "NOT_RPYTHON"
    ob = _pypy2ob.get(p)
    if ob is None:
        return lltype.nullptr(OB_PTR_TYPE.TO)
    assert lltype.typeOf(ob) == OB_PTR_TYPE
    return ob

def to_obj(Class, ob):
    "NOT_RPYTHON"
    link = ob.c_ob_pypy_link
    if link == 0:
        return None
    p = _adr2pypy[link]
    assert isinstance(p, Class)
    return p

def _collect(track_allocation=True):
    """NOT_RPYTHON: for tests only.  Emulates a GC collection.
    Will invoke dealloc_callback() for all objects whose _Py_Dealloc()
    should be called.
    """
    def detach(ob, wr_list):
        assert ob.c_ob_refcnt >= REFCNT_FROM_PYPY
        assert ob.c_ob_pypy_link
        p = _adr2pypy[ob.c_ob_pypy_link]
        assert p is not None
        _adr2pypy[ob.c_ob_pypy_link] = None
        wr_list.append((ob, weakref.ref(p)))
        return p

    global _p_list, _o_list
    wr_p_list = []
    new_p_list = []
    for ob in _p_list:
        if ob.c_ob_refcnt not in (REFCNT_FROM_PYPY, REFCNT_FROM_PYPY_LIGHT):
            new_p_list.append(ob)
        else:
            p = detach(ob, wr_p_list)
            del _pypy2ob[p]
            del p
        ob = None
    _p_list = Ellipsis

    wr_o_list = []
    for ob in _o_list:
        detach(ob, wr_o_list)
    _o_list = Ellipsis

    rgc.collect()  # forces the cycles to be resolved and the weakrefs to die
    rgc.collect()
    rgc.collect()

    def attach(ob, wr, final_list):
        assert ob.c_ob_refcnt >= REFCNT_FROM_PYPY
        p = wr()
        if p is not None:
            assert ob.c_ob_pypy_link
            _adr2pypy[ob.c_ob_pypy_link] = p
            final_list.append(ob)
            return p
        else:
            ob.c_ob_pypy_link = 0
            if ob.c_ob_refcnt >= REFCNT_FROM_PYPY_LIGHT:
                assert ob.c_ob_refcnt == REFCNT_FROM_PYPY_LIGHT
                lltype.free(ob, flavor='raw', track_allocation=track_allocation)
            else:
                assert ob.c_ob_refcnt >= REFCNT_FROM_PYPY
                assert ob.c_ob_refcnt < int(REFCNT_FROM_PYPY_LIGHT * 0.99)
                ob.c_ob_refcnt -= REFCNT_FROM_PYPY
                ob.c_ob_pypy_link = 0
                if ob.c_ob_refcnt == 0:
                    _dealloc_callback(ob)
            return None

    _p_list = new_p_list
    for ob, wr in wr_p_list:
        p = attach(ob, wr, _p_list)
        if p:
            _pypy2ob[p] = ob
    _o_list = []
    for ob, wr in wr_o_list:
        attach(ob, wr, _o_list)

# ____________________________________________________________


def _unspec_p(hop, v_p):
    assert isinstance(v_p.concretetype, lltype.Ptr)
    assert v_p.concretetype.TO._gckind == 'gc'
    return hop.genop('cast_opaque_ptr', [v_p], resulttype=llmemory.GCREF)

def _unspec_ob(hop, v_ob):
    assert isinstance(v_ob.concretetype, lltype.Ptr)
    assert v_ob.concretetype.TO._gckind == 'raw'
    return hop.genop('cast_ptr_to_adr', [v_ob], resulttype=llmemory.Address)

def _spec_p(hop, v_p):
    assert v_p.concretetype == llmemory.GCREF
    return hop.genop('cast_opaque_ptr', [v_p],
                     resulttype=hop.r_result.lowleveltype)

def _spec_ob(hop, v_ob):
    assert v_ob.concretetype == llmemory.Address
    return hop.genop('cast_adr_to_ptr', [v_ob],
                     resulttype=hop.r_result.lowleveltype)


class Entry(ExtRegistryEntry):
    _about_ = init

    def compute_result_annotation(self, s_dealloc_callback):
        from rpython.rtyper.llannotation import SomePtr
        assert isinstance(s_dealloc_callback, SomePtr)   # ll-ptr-to-function

    def specialize_call(self, hop):
        hop.exception_cannot_occur()
        [v_dealloc_callback] = hop.inputargs(hop.args_r[0])
        hop.genop('gc_rawrefcount_init', [v_dealloc_callback])


class Entry(ExtRegistryEntry):
    _about_ = (create_link_pypy, create_link_pyobj)

    def compute_result_annotation(self, s_p, s_ob):
        pass

    def specialize_call(self, hop):
        if self.instance is create_link_pypy:
            name = 'gc_rawrefcount_create_link_pypy'
        elif self.instance is create_link_pyobj:
            name = 'gc_rawrefcount_create_link_pyobj'
        v_p, v_ob = hop.inputargs(*hop.args_r)
        hop.exception_cannot_occur()
        hop.genop(name, [_unspec_p(hop, v_p), _unspec_ob(hop, v_ob)])


class Entry(ExtRegistryEntry):
    _about_ = from_obj

    def compute_result_annotation(self, s_OB_PTR_TYPE, s_p):
        from rpython.annotator import model as annmodel
        from rpython.rtyper.llannotation import lltype_to_annotation
        assert (isinstance(s_p, annmodel.SomeInstance) or
                    annmodel.s_None.contains(s_p))
        assert s_OB_PTR_TYPE.is_constant()
        return lltype_to_annotation(s_OB_PTR_TYPE.const)

    def specialize_call(self, hop):
        hop.exception_cannot_occur()
        v_p = hop.inputarg(hop.args_r[1], arg=1)
        v_ob = hop.genop('gc_rawrefcount_from_obj', [_unspec_p(hop, v_p)],
                         resulttype = llmemory.Address)
        return _spec_ob(hop, v_ob)

class Entry(ExtRegistryEntry):
    _about_ = to_obj

    def compute_result_annotation(self, s_Class, s_ob):
        from rpython.annotator import model as annmodel
        from rpython.rtyper.llannotation import SomePtr
        assert isinstance(s_ob, SomePtr)
        assert s_Class.is_constant()
        classdef = self.bookkeeper.getuniqueclassdef(s_Class.const)
        return annmodel.SomeInstance(classdef, can_be_None=True)

    def specialize_call(self, hop):
        hop.exception_cannot_occur()
        v_ob = hop.inputarg(hop.args_r[1], arg=1)
        v_p = hop.genop('gc_rawrefcount_to_obj', [_unspec_ob(hop, v_ob)],
                        resulttype = llmemory.GCREF)
        return _spec_p(hop, v_p)
