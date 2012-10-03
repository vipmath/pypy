from pypy.annotation.listdef import s_list_of_strings
from pypy.annotation.model import SomeInteger
from pypy.objspace.flow.model import Constant, SpaceOperation
from pypy.rpython.lltypesystem import lltype, rffi
from pypy.rpython.memory.gc.marksweep import MarkSweepGC
from pypy.rpython.memory.gctransform.framework import (CollectAnalyzer,
     find_initializing_stores, find_clean_setarrayitems)
from pypy.rpython.memory.gctransform.shadowstack import (
     ShadowStackFrameworkGCTransformer)
from pypy.rpython.memory.gctransform.test.test_transform import rtype
from pypy.rpython.memory.gctransform.transform import GcHighLevelOp
from pypy.rpython.rtyper import LowLevelOpList
from pypy.translator.backendopt.all import backend_optimizations
from pypy.translator.c.gc import BasicFrameworkGcPolicy
from pypy.translator.exceptiontransform import ExceptionTransformer
from pypy.translator.translator import TranslationContext, graphof
from pypy.translator.unsimplify import varoftype

import py

class FrameworkGcPolicy2(BasicFrameworkGcPolicy):
    class transformerclass(ShadowStackFrameworkGCTransformer):
        root_stack_depth = 100

def test_framework_simple():
    def g(x):
        return x + 1
    class A(object):
        pass
    def entrypoint(argv):
        a = A()
        a.b = g(1)
        return a.b

    from pypy.rpython.llinterp import LLInterpreter
    from pypy.translator.c.genc import CStandaloneBuilder

    t = rtype(entrypoint, [s_list_of_strings])
    cbuild = CStandaloneBuilder(t, entrypoint, t.config,
                                gcpolicy=FrameworkGcPolicy2)
    db = cbuild.generate_graphs_for_llinterp()
    entrypointptr = cbuild.getentrypointptr()
    entrygraph = entrypointptr._obj.graph

    llinterp = LLInterpreter(t.rtyper)

    # FIIIIISH
    setupgraph = db.gctransformer.frameworkgc_setup_ptr.value._obj.graph
    llinterp.eval_graph(setupgraph, [])

    res = llinterp.eval_entry_point(entrygraph, [])

    assert res == 2

def test_cancollect():
    S = lltype.GcStruct('S', ('x', lltype.Signed))
    def g():
        lltype.malloc(S, zero=True)
    t = rtype(g, [])
    gg = graphof(t, g)
    assert CollectAnalyzer(t).analyze_direct_call(gg)

    def g(x):
        return -x
    t = rtype(g, [int])
    gg = graphof(t, g)
    assert not CollectAnalyzer(t).analyze_direct_call(gg)    

def test_cancollect_external():
    fext1 = rffi.llexternal('fext1', [], lltype.Void, threadsafe=False)
    def g():
        fext1()
    t = rtype(g, [])
    gg = graphof(t, g)
    assert not CollectAnalyzer(t).analyze_direct_call(gg)

    fext2 = rffi.llexternal('fext2', [], lltype.Void, threadsafe=True)
    def g():
        fext2()
    t = rtype(g, [])
    gg = graphof(t, g)
    assert CollectAnalyzer(t).analyze_direct_call(gg)

    S = lltype.GcStruct('S', ('x', lltype.Signed))
    FUNC = lltype.Ptr(lltype.FuncType([lltype.Signed], lltype.Void))
    fext3 = rffi.llexternal('fext3', [FUNC], lltype.Void, threadsafe=False)
    def h(x):
        lltype.malloc(S, zero=True)
    def g():
        fext3(h)
    t = rtype(g, [])
    gg = graphof(t, g)
    assert CollectAnalyzer(t).analyze_direct_call(gg)

def test_no_collect():
    from pypy.rlib import rgc
    from pypy.translator.c.genc import CStandaloneBuilder

    @rgc.no_collect
    def g():
        return 1

    assert g._dont_inline_
    assert g._gc_no_collect_

    def entrypoint(argv):
        return g() + 2
    
    t = rtype(entrypoint, [s_list_of_strings])
    cbuild = CStandaloneBuilder(t, entrypoint, t.config,
                                gcpolicy=FrameworkGcPolicy2)
    db = cbuild.generate_graphs_for_llinterp()

def test_no_collect_detection():
    from pypy.rlib import rgc
    from pypy.translator.c.genc import CStandaloneBuilder

    class A(object):
        def __init__(self, x):
            self.x = x

    @rgc.no_collect
    def g():
        return A(1).x

    assert g._dont_inline_
    assert g._gc_no_collect_

    def entrypoint(argv):
        return g() + 2
    
    t = rtype(entrypoint, [s_list_of_strings])
    cbuild = CStandaloneBuilder(t, entrypoint, t.config,
                                gcpolicy=FrameworkGcPolicy2)
    f = py.test.raises(Exception, cbuild.generate_graphs_for_llinterp)
    expected = "'no_collect' function can trigger collection: <function g at "
    assert str(f.value).startswith(expected)

class WriteBarrierTransformer(ShadowStackFrameworkGCTransformer):
    clean_sets = {}
    GC_PARAMS = {}
    class GCClass(MarkSweepGC):
        needs_write_barrier = True
        def writebarrier_before_copy(self, source, dest,
                                     source_start, dest_start, length):
            return True

def write_barrier_check(spaceop, needs_write_barrier=True):
    t = TranslationContext()
    t.buildannotator().build_types(lambda x:x, [SomeInteger()])
    t.buildrtyper().specialize()
    transformer = WriteBarrierTransformer(t)
    llops = LowLevelOpList()
    hop = GcHighLevelOp(transformer, spaceop, 0, llops)
    hop.dispatch()
    found = False
    print spaceop, '======>'
    for op in llops:
        print '\t', op
        if op.opname == 'direct_call':
            found = True
    assert found == needs_write_barrier

def test_write_barrier_support_setfield():
    PTR_TYPE2 = lltype.Ptr(lltype.GcStruct('T', ('y', lltype.Signed)))
    PTR_TYPE = lltype.Ptr(lltype.GcStruct('S', ('x', PTR_TYPE2)))
    write_barrier_check(SpaceOperation(
        "setfield",
        [varoftype(PTR_TYPE), Constant('x', lltype.Void),
         varoftype(PTR_TYPE2)],
        varoftype(lltype.Void)))


def test_dont_add_write_barrier_for_constant_new_value():
    PTR_TYPE2 = lltype.Ptr(lltype.GcStruct('T', ('y', lltype.Signed)))
    PTR_TYPE = lltype.Ptr(lltype.GcStruct('S', ('x', PTR_TYPE2)))
    write_barrier_check(SpaceOperation(
        "setfield",
        [varoftype(PTR_TYPE), Constant('x', lltype.Void),
         Constant('foo', varoftype(PTR_TYPE2))],
        varoftype(lltype.Void)), needs_write_barrier=False)

def test_write_barrier_support_setarrayitem():
    PTR_TYPE2 = lltype.Ptr(lltype.GcStruct('T', ('y', lltype.Signed)))
    ARRAYPTR = lltype.Ptr(lltype.GcArray(PTR_TYPE2))
    write_barrier_check(SpaceOperation(
        "setarrayitem",
        [varoftype(ARRAYPTR), varoftype(lltype.Signed),
         varoftype(PTR_TYPE2)],
        varoftype(lltype.Void)))

def test_write_barrier_support_setinteriorfield():
    PTR_TYPE2 = lltype.Ptr(lltype.GcStruct('T', ('y', lltype.Signed)))
    ARRAYPTR2 = lltype.Ptr(lltype.GcArray(('a', lltype.Signed),
                                          ('b', PTR_TYPE2)))
    write_barrier_check(SpaceOperation(
        "setinteriorfield",
        [varoftype(ARRAYPTR2), varoftype(lltype.Signed),
         Constant('b', lltype.Void), varoftype(PTR_TYPE2)],
        varoftype(lltype.Void)))

def test_find_initializing_stores():

    class A(object):
        pass
    class B(object):
        pass
    def f():
        a = A()
        b = B()
        b.a = a
        b.b = 1
    t = rtype(f, [])
    etrafo = ExceptionTransformer(t)
    graphs = etrafo.transform_completely()
    collect_analyzer = CollectAnalyzer(t)
    init_stores = find_initializing_stores(collect_analyzer, t.graphs[0])
    assert len(init_stores) == 1

def test_find_initializing_stores_across_blocks():

    class A(object):
        pass
    class B(object):
        pass
    def f(x):
        a1 = A()
        a2 = A()
        a = A()
        b = B()
        b.a = a
        if x:
            b.b = a1
            b.c = a2
        else:
            b.c = a1
            b.b = a2
    t = rtype(f, [int])
    etrafo = ExceptionTransformer(t)
    graphs = etrafo.transform_completely()
    collect_analyzer = CollectAnalyzer(t)
    init_stores = find_initializing_stores(collect_analyzer, t.graphs[0])
    assert len(init_stores) == 5

def test_find_clean_setarrayitems():
    S = lltype.GcStruct('S')
    A = lltype.GcArray(lltype.Ptr(S))
    
    def f():
        l = lltype.malloc(A, 3)
        l[0] = lltype.malloc(S)
        l[1] = lltype.malloc(S)
        l[2] = lltype.malloc(S)
        x = l[1]
        l[0] = x
        return len(l)

    t = rtype(f, [])
    etrafo = ExceptionTransformer(t)
    graph = etrafo.transform_completely()
    collect_analyzer = CollectAnalyzer(t)
    clean_setarrayitems = find_clean_setarrayitems(collect_analyzer,
                                                   t.graphs[0])
    assert len(clean_setarrayitems) == 1

def test_find_clean_setarrayitems_2():
    S = lltype.GcStruct('S')
    A = lltype.GcArray(lltype.Ptr(S))
    
    def f():
        l = lltype.malloc(A, 3)
        l[0] = lltype.malloc(S)
        l[1] = lltype.malloc(S)
        l[2] = lltype.malloc(S)
        x = l[1]
        l[2] = lltype.malloc(S) # <- this can possibly collect
        l[0] = x
        return len(l)

    t = rtype(f, [])
    etrafo = ExceptionTransformer(t)
    graph = etrafo.transform_completely()
    collect_analyzer = CollectAnalyzer(t)
    clean_setarrayitems = find_clean_setarrayitems(collect_analyzer,
                                                   t.graphs[0])
    assert len(clean_setarrayitems) == 0

def test_find_clean_setarrayitems_3():
    S = lltype.GcStruct('S')
    A = lltype.GcArray(lltype.Ptr(S))
    
    def f():
        l = lltype.malloc(A, 3)
        l[0] = lltype.malloc(S)
        l[1] = lltype.malloc(S)
        l[2] = lltype.malloc(S)
        l2 = lltype.malloc(A, 4)
        x = l[1]
        l2[0] = x # <- different list
        return len(l)

    t = rtype(f, [])
    etrafo = ExceptionTransformer(t)
    graph = etrafo.transform_completely()
    collect_analyzer = CollectAnalyzer(t)
    clean_setarrayitems = find_clean_setarrayitems(collect_analyzer,
                                                   t.graphs[0])
    assert len(clean_setarrayitems) == 0

def test_list_operations():

    class A(object):
        pass

    def f():
        l = [A(), A()]
        l.append(A())
        l[1] = l[0]
        return len(l)

    t = rtype(f, [])
    backend_optimizations(t, clever_malloc_removal=False, storesink=True)
    etrafo = ExceptionTransformer(t)
    graph = etrafo.transform_completely()
    collect_analyzer = CollectAnalyzer(t)
    clean_setarrayitems = find_clean_setarrayitems(collect_analyzer,
                                                   t.graphs[0])
    assert len(clean_setarrayitems) == 1
