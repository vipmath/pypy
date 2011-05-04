from pypy.module.micronumpy.numarray import SingleDimArray, BinOp, FloatWrapper
from pypy.jit.metainterp.test.support import LLJitMixin

class FakeSpace(object):
    pass

class TestNumpyJIt(LLJitMixin):
    def setup_class(cls):
        cls.space = FakeSpace()
    
    def test_add(self):
        space = self.space
        
        def f(i):
            ar = SingleDimArray(i)
            if i:
                v = BinOp('a', ar, ar)
            else:
                v = ar
            return v.force().storage[3]

        result = self.meta_interp(f, [5], listops=True, backendopt=True)
        self.check_loops({'getarrayitem_raw': 2, 'float_add': 1,
                          'setarrayitem_raw': 1, 'int_add': 1,
                          'int_lt': 1, 'guard_true': 1, 'jump': 1})
        assert result == f(5)

    def test_floatadd(self):
        space = self.space

        def f(i):
            ar = SingleDimArray(i)
            if i:
                v = BinOp('a', ar, FloatWrapper(4.5))
            else:
                v = ar
            return v.force().storage[3]

        result = self.meta_interp(f, [5], listops=True, backendopt=True)
        self.check_loops({"getarrayitem_raw": 1, "float_add": 1,
                          "setarrayitem_raw": 1, "int_add": 1,
                          "int_lt": 1, "guard_true": 1, "jump": 1})
        assert result == f(5)
