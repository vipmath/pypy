import pytest
from rpython.jit.metainterp.optimizeopt.test.test_util import (
    LLtypeMixin)
from rpython.jit.metainterp.optimizeopt.test.test_optimizebasic import (
    BaseTestBasic)
from rpython.jit.metainterp.optimizeopt.test.test_optimizeopt import (
    BaseTestWithUnroll)
from rpython.jit.metainterp.history import ConstInt, ConstPtr
from rpython.jit.metainterp.optimize import InvalidLoop

class TestCompatible(BaseTestBasic, LLtypeMixin):

    enable_opts = "intbounds:rewrite:virtualize:string:earlyforce:pure:heap"

    def test_guard_compatible_and_guard_value(self):
        ops = """
        [p1]
        guard_value(p1, ConstPtr(myptr)) []
        guard_compatible(p1, ConstPtr(myptr)) []
        jump(ConstPtr(myptr))
        """
        expected = """
        [p1]
        guard_value(p1, ConstPtr(myptr)) []
        jump(ConstPtr(myptr))
        """
        self.optimize_loop(ops, expected)

        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        guard_value(p1, ConstPtr(myptr)) []
        jump(ConstPtr(myptr))
        """
        self.optimize_loop(ops, expected)

    def test_guard_compatible_and_guard_nonnull(self):
        ops = """
        [p1]
        guard_nonnull(p1) []
        guard_compatible(p1, ConstPtr(myptr)) []
        guard_nonnull(p1) []
        jump(ConstPtr(myptr))
        """
        expected = """
        [p1]
        guard_nonnull(p1) []
        guard_compatible(p1, ConstPtr(myptr)) []
        jump(ConstPtr(myptr))
        """
        self.optimize_loop(ops, expected)

    def test_guard_compatible_and_guard_class(self):
        ops = """
        [p1]
        guard_class(p1, ConstClass(node_vtable)) []
        guard_compatible(p1, ConstPtr(myptr)) []
        guard_class(p1, ConstClass(node_vtable)) []
        jump(ConstPtr(myptr))
        """
        expected = """
        [p1]
        guard_class(p1, ConstClass(node_vtable)) []
        guard_compatible(p1, ConstPtr(myptr)) []
        jump(ConstPtr(myptr))
        """
        self.optimize_loop(ops, expected)

    def test_guard_compatible_after_guard_compatible(self):
        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        guard_compatible(p1, ConstPtr(myptr)) []
        jump(ConstPtr(myptr))
        """
        expected = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        jump(ConstPtr(myptr))
        """
        self.optimize_loop(ops, expected)

    def test_guard_compatible_inconsistent(self):
        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        guard_compatible(p1, ConstPtr(myptrb)) []
        jump(ConstPtr(myptr))
        """
        pytest.raises(InvalidLoop, self.optimize_loop, ops, ops)

    def test_guard_compatible_call_pure(self):
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.myptr)): ConstInt(5),
            (ConstInt(124), ConstPtr(self.myptr)): ConstInt(7),
        }
        ops1 = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        i3 = call_pure_i(123, p1, descr=plaincalldescr)
        escape_n(i3)
        i5 = call_pure_i(124, p1, descr=plaincalldescr)
        escape_n(i5)
        jump(ConstPtr(myptr))
        """
        ops2 = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        i3 = call_pure_i(123, p1, descr=plaincalldescr)
        escape_n(i3)
        guard_compatible(p1, ConstPtr(myptr)) []
        i5 = call_pure_i(124, p1, descr=plaincalldescr)
        escape_n(i5)
        jump(ConstPtr(myptr))
        """
        expected = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        escape_n(5)
        escape_n(7)
        jump(ConstPtr(myptr))
        """
        for ops in [ops1, ops2]:
            self.optimize_loop(ops, expected, call_pure_results=call_pure_results)
            # whitebox-test the guard_compatible descr a bit
            descr = self.loop.operations[1].getdescr()
            assert descr._compatibility_conditions is not None
            assert descr._compatibility_conditions.known_valid.same_constant(ConstPtr(self.myptr))
            assert len(descr._compatibility_conditions.conditions) == 2

    def test_guard_compatible_call_pure_late_constant(self):
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.myptr), ConstInt(5)): ConstInt(5),
            (ConstInt(124), ConstPtr(self.myptr), ConstInt(5)): ConstInt(7),
        }
        ops = """
        [p1]
        pvirtual = new_with_vtable(descr=nodesize)
        setfield_gc(pvirtual, 5, descr=valuedescr)
        i1 = getfield_gc_i(pvirtual, descr=valuedescr)
        guard_compatible(p1, ConstPtr(myptr)) []
        i3 = call_pure_i(123, p1, i1, descr=plaincalldescr)
        escape_n(i3)
        i5 = call_pure_i(124, p1, i1, descr=plaincalldescr)
        escape_n(i5)
        jump(ConstPtr(myptr))
        """
        expected = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        escape_n(5)
        escape_n(7)
        jump(ConstPtr(myptr))
        """
        self.optimize_loop(ops, expected, call_pure_results=call_pure_results)
        # whitebox-test the guard_compatible descr a bit
        descr = self.loop.operations[1].getdescr()
        assert descr._compatibility_conditions is not None
        assert descr._compatibility_conditions.known_valid.same_constant(ConstPtr(self.myptr))
        assert len(descr._compatibility_conditions.conditions) == 2

    def test_guard_compatible_call_pure_not_const(self):
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.myptr), ConstInt(5), ConstInt(5)): ConstInt(5),
            (ConstInt(124), ConstPtr(self.myptr), ConstInt(5), ConstInt(5)): ConstInt(7),
        }
        ops = """
        [p1, i2]
        pvirtual = new_with_vtable(descr=nodesize)
        setfield_gc(pvirtual, 5, descr=valuedescr)
        i1 = getfield_gc_i(pvirtual, descr=valuedescr)
        guard_compatible(p1, ConstPtr(myptr)) []
        i3 = call_pure_i(123, p1, i1, i2, descr=plaincalldescr)
        escape_n(i3)
        i5 = call_pure_i(124, p1, i1, i2, descr=plaincalldescr)
        escape_n(i5)
        jump(ConstPtr(myptr), 5)
        """
        expected = """
        [p1, i2]
        guard_compatible(p1, ConstPtr(myptr)) []
        i3 = call_i(123, p1, 5, i2, descr=plaincalldescr)
        escape_n(i3)
        i5 = call_i(124, p1, 5, i2, descr=plaincalldescr)
        escape_n(i5)
        jump(ConstPtr(myptr), 5)
        """
        self.optimize_loop(ops, expected, call_pure_results=call_pure_results)

    def test_deduplicate_conditions(self):
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.myptr)): ConstInt(5),
        }
        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        i3 = call_pure_i(123, p1, descr=plaincalldescr)
        i4 = call_pure_i(123, p1, descr=plaincalldescr)
        i5 = call_pure_i(123, p1, descr=plaincalldescr)
        i6 = call_pure_i(123, p1, descr=plaincalldescr)
        escape_n(i3)
        escape_n(i4)
        escape_n(i5)
        escape_n(i6)
        jump(ConstPtr(myptr))
        """
        expected = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        escape_n(5)
        escape_n(5)
        escape_n(5)
        escape_n(5)
        jump(ConstPtr(myptr))
        """
        self.optimize_loop(ops, expected, call_pure_results=call_pure_results)
        descr = self.loop.operations[1].getdescr()
        assert descr._compatibility_conditions is not None
        assert descr._compatibility_conditions.known_valid.same_constant(ConstPtr(self.myptr))
        assert len(descr._compatibility_conditions.conditions) == 1

    def test_quasiimmut(self):
        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        quasiimmut_field(p1, descr=quasiimmutdescr)
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr)
        i1 = call_pure_i(123, p1, i0, descr=nonwritedescr)
        quasiimmut_field(p1, descr=quasiimmutdescr)
        guard_not_invalidated() []
        i3 = getfield_gc_i(p1, descr=quasifielddescr)
        i4 = call_pure_i(123, p1, i3, descr=nonwritedescr)
        escape_n(i1)
        escape_n(i4)
        jump(p1)
        """
        expected = """
        [p1]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr) # will be removed by the backend
        escape_n(5)
        escape_n(5)
        jump(p1)
        """
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.quasiptr), ConstInt(-4247)): ConstInt(5),
        }
        self.optimize_loop(ops, expected, call_pure_results)
        descr = self.loop.operations[1].getdescr()
        assert descr._compatibility_conditions is not None
        assert descr._compatibility_conditions.known_valid.same_constant(ConstPtr(self.quasiptr))
        assert len(descr._compatibility_conditions.conditions) == 1

    def test_quasiimmut_nonconst(self):
        ops = """
        [p1, i5]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        quasiimmut_field(p1, descr=quasiimmutdescr)
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr)
        i1 = call_pure_i(123, p1, i0, i5, descr=nonwritedescr)
        i4 = call_pure_i(123, p1, i0, i5, descr=nonwritedescr)
        escape_n(i1)
        escape_n(i4)
        jump(p1, i5)
        """
        expected = """
        [p1, i5]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr) # will be removed by the backend
        i1 = call_i(123, p1, i0, i5, descr=nonwritedescr)
        escape_n(i1)
        escape_n(i1)
        jump(p1, i5)
        """
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.quasiptr), ConstInt(-4247)): ConstInt(5),
        }
        self.optimize_loop(ops, expected, call_pure_results)

    def test_quasiimmut_bug(self):
        # bug that happened because we hade quasiimmut_field on two different
        # boxes (that turn out to be the same after other optimizations)
        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        quasiimmut_field(p1, descr=quasiimmutdescr)
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr)
        i1 = call_pure_i(123, p1, i0, descr=nonwritedescr)

        # get an alias p2 to p1
        p3 = new_with_vtable(descr=nodesize)
        setfield_gc(p3, p1, descr=nextdescr)
        p2 = getfield_gc_r(p3, descr=nextdescr)

        # a condition via the alias
        guard_compatible(p2, ConstPtr(quasiptr)) []
        quasiimmut_field(p2, descr=quasiimmutdescr)
        guard_not_invalidated() []
        i3 = getfield_gc_i(p2, descr=quasifielddescr)
        i4 = call_pure_i(123, p2, i3, descr=nonwritedescr)

        # and now the original box
        i5 = call_pure_i(123, p1, i0, descr=nonwritedescr)
        escape_n(i1)
        escape_n(i4)
        escape_n(i5)
        jump(p1)
        """
        expected = """
        [p1]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr) # will be removed by the backend
        escape_n(5)
        escape_n(5)
        escape_n(5)
        jump(p1)
        """
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.quasiptr), ConstInt(-4247)): ConstInt(5),
        }
        self.optimize_loop(ops, expected, call_pure_results)
        descr = self.loop.operations[1].getdescr()
        assert descr._compatibility_conditions is not None
        assert descr._compatibility_conditions.known_valid.same_constant(ConstPtr(self.quasiptr))
        assert len(descr._compatibility_conditions.conditions) == 1


class TestCompatibleUnroll(BaseTestWithUnroll, LLtypeMixin):

    def test_remove_guard_compatible(self):
        ops = """
        [p0]
        guard_compatible(p0, ConstPtr(myptr)) []
        guard_compatible(p0, ConstPtr(myptr)) []
        jump(p0)
        """
        preamble = """
        [p0]
        guard_compatible(p0, ConstPtr(myptr)) []
        jump(p0)
        """
        expected = """
        [p0]
        jump(p0)
        """
        self.optimize_loop(ops, expected, expected_preamble=preamble)


    def test_guard_compatible_call_pure(self):
        call_pure_results = {
            (ConstInt(123), ConstPtr(self.myptr)): ConstInt(5),
            (ConstInt(124), ConstPtr(self.myptr)): ConstInt(7),
        }
        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        i3 = call_pure_i(123, p1, descr=plaincalldescr)
        escape_n(i3)
        guard_compatible(p1, ConstPtr(myptr)) []
        i5 = call_pure_i(124, p1, descr=plaincalldescr)
        escape_n(i5)
        jump(p1)
        """
        preamble = """
        [p1]
        guard_compatible(p1, ConstPtr(myptr)) []
        escape_n(5)
        escape_n(7)
        jump(p1)
        """
        expected = """
        [p0]
        escape_n(5)
        escape_n(7)
        jump(p0)
        """
        self.optimize_loop(ops, expected, expected_preamble=preamble, call_pure_results=call_pure_results)
        # whitebox-test the guard_compatible descr a bit
        descr = self.preamble.operations[1].getdescr()
        assert descr._compatibility_conditions is not None
        assert descr._compatibility_conditions.known_valid.same_constant(ConstPtr(self.myptr))
        assert len(descr._compatibility_conditions.conditions) == 2

    def test_quasiimmut(self):
        ops = """
        [p1]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        quasiimmut_field(p1, descr=quasiimmutdescr)
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr)
        i1 = call_pure_i(123, p1, i0, descr=nonwritedescr)
        quasiimmut_field(p1, descr=quasiimmutdescr)
        guard_not_invalidated() []
        i3 = getfield_gc_i(p1, descr=quasifielddescr)
        i4 = call_pure_i(123, p1, i3, descr=nonwritedescr)
        escape_n(i1)
        escape_n(i4)
        jump(p1)
        """
        preamble = """
        [p1]
        guard_compatible(p1, ConstPtr(quasiptr)) []
        guard_not_invalidated() []
        i0 = getfield_gc_i(p1, descr=quasifielddescr) # will be removed by the backend
        escape_n(5)
        escape_n(5)
        jump(p1)
        """
        expected = """
        [p1]
        guard_not_invalidated() []
        escape_n(5)
        escape_n(5)
        jump(p1)
        """

        call_pure_results = {
            (ConstInt(123), ConstPtr(self.quasiptr), ConstInt(-4247)): ConstInt(5),
        }
        self.optimize_loop(ops, expected, expected_preamble=preamble, call_pure_results=call_pure_results)
        descr = self.preamble.operations[1].getdescr()
        assert descr._compatibility_conditions is not None
        assert descr._compatibility_conditions.known_valid.same_constant(ConstPtr(self.quasiptr))
        assert len(descr._compatibility_conditions.conditions) == 1