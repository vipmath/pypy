"""miscelanneous utility functions

XXX: svn mv pythonutil.py gramtools.py / parsertools.py
"""

import sys
import os
import parser

from pypy.interpreter.pyparser.grammar import Parser
from pypy.interpreter.pyparser.pytoken import setup_tokens
from pypy.interpreter.pyparser.ebnfgrammar import GRAMMAR_GRAMMAR
from pypy.interpreter.pyparser.ebnflexer import GrammarSource
from pypy.interpreter.pyparser.ebnfparse import EBNFBuilder

from pypy.interpreter.pyparser.tuplebuilder import TupleBuilder

PYTHON_VERSION = ".".join([str(i) for i in sys.version_info[:2]])

def get_grammar_file(version):
    """returns the python grammar corresponding to our CPython version"""
    if version == "native":
        _ver = PYTHON_VERSION
    elif version == "stable":
        _ver = "_stablecompiler"
    elif version in ("2.3","2.4","2.5a"):
        _ver = version
    return os.path.join( os.path.dirname(__file__), "data", "Grammar" + _ver ), _ver


def build_parser(gramfile, parser=None):
    """reads a (EBNF) grammar definition and builds a parser for it"""
    if parser is None:
        parser = Parser()
    setup_tokens(parser)
    # XXX: clean up object dependencies
    source = GrammarSource(GRAMMAR_GRAMMAR, file(gramfile).read())
    builder = EBNFBuilder(GRAMMAR_GRAMMAR, dest_parser=parser)
    GRAMMAR_GRAMMAR.root_rules['grammar'].match(source, builder)
    builder.resolve_rules()
    parser.build_first_sets()
    return parser


def build_parser_for_version(version, parser=None):
    gramfile, _ = get_grammar_file(version)
    return build_parser(gramfile, parser)


## XXX: the below code should probably go elsewhere 

## convenience functions for computing AST objects using recparser
def ast_from_input(input, mode, transformer, parser):
    """converts a source input into an AST

     - input : the source to be converted
     - mode : 'exec', 'eval' or 'single'
     - transformer : the transfomer instance to use to convert
                     the nested tuples into the AST
     XXX: transformer could be instantiated here but we don't want
          here to explicitly import compiler or stablecompiler or
          etc. This is to be fixed in a clean way
    """
    builder = TupleBuilder(parser, lineno=True)
    parser.parse_source(input, mode, builder)
    tuples = builder.stack[-1].as_tuple(True)
    return transformer.compile_node(tuples)


def pypy_parse(source, mode='exec', lineno=False):
    from pypy.interpreter.pyparser.pythonparse import PythonParser, get_pyparser_for_version
    from pypy.interpreter.pyparser.astbuilder import AstBuilder
    # parser = build_parser_for_version("2.4", PythonParser())
    parser = get_pyparser_for_version('2.4')
    builder = TupleBuilder(parser)
    parser.parse_source(source, mode, builder)
    return builder.stack[-1].as_tuple(lineno)


def source2ast(source, mode='exec', version='2.4', space=None):
    from pypy.interpreter.pyparser.pythonparse import PythonParser, get_pyparser_for_version
    from pypy.interpreter.pyparser.astbuilder import AstBuilder
    parser = get_pyparser_for_version(version)
    builder = AstBuilder(parser, space=space)
    parser.parse_source(source, mode, builder)
    return builder
    

## convenience functions around CPython's parser functions
def python_parsefile(filename, lineno=False):
    """parse <filename> using CPython's parser module and return nested tuples
    """
    pyf = file(filename)
    source = pyf.read()
    pyf.close()
    return python_parse(source, 'exec', lineno)

def python_parse(source, mode='exec', lineno=False):
    """parse python source using CPython's parser module and return
    nested tuples
    """
    if mode == 'eval':
        tp = parser.expr(source)
    else:
        tp = parser.suite(source)
    return parser.ast2tuple(tp, line_info=lineno)

def pypy_parsefile(filename, lineno=False):
    """parse <filename> using PyPy's parser module and return
    a tuple of three elements :
     - The encoding declaration symbol or None if there were no encoding
       statement
     - The TupleBuilder's stack top element (instance of
       tuplebuilder.StackElement which is a wrapper of some nested tuples
       like those returned by the CPython's parser)
     - The encoding string or None if there were no encoding statement
    nested tuples
    """
    pyf = file(filename)
    source = pyf.read()
    pyf.close()
    return pypy_parse(source, 'exec', lineno)
