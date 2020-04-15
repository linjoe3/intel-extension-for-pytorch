from __future__ import print_function

import argparse
import collections
import lark
import os
import re
import string
import sys


def namedtuple_with_defaults(typename, field_names, default_values=()):
    ntuple = collections.namedtuple(typename, field_names)
    ntuple.__new__.__defaults__ = (None,) * len(ntuple._fields)
    if isinstance(default_values, collections.Mapping):
        prototype = ntuple(**default_values)
    else:
        prototype = ntuple(*default_values)
    ntuple.__new__.__defaults__ = tuple(prototype)
    return ntuple

FuncDef = namedtuple_with_defaults('FuncDef', 'cpp_sig, aten_sig')

FuncGen = namedtuple_with_defaults(
    'FuncGen',
    'tree, xtree, rwxtree, func, xfunc, code, sig, rwsig, cppsig, funsig, mapsig, aten_sig'
)

_GRAMMAR = r"""
    start: type fnname "(" params ")"
    type: CONST? core_type refspec?
    fnname: CNAME
    refspec: REF
           | PTR
    core_type: template
        | TNAME
    template: TNAME "<" typelist ">"
    typelist: type
            | type "," typelist
    REF: "&"
    PTR: "*"
    CONST: "const"
    TNAME: /[a-zA-Z0-9_:]+/
    HEXNUMBER: /0x[0-9a-fA-F]+/
    params: param
          | param "," params
    param: type param_name param_defval?
    param_name: CNAME

    param_defval: "=" init_value
    init_value: "true"
              | "false"
              | "{}"
              | NUMBER
              | SIGNED_NUMBER
              | HEXNUMBER
              | ESCAPED_STRING

    %import common.CNAME -> CNAME
    %import common.NUMBER -> NUMBER
    %import common.SIGNED_NUMBER -> SIGNED_NUMBER
    %import common.ESCAPED_STRING -> ESCAPED_STRING
    %import common.WS
    %ignore WS
    """

_PARSER = lark.Lark(_GRAMMAR, parser='lalr', propagate_positions=True)

_XPARSER = lark.Lark(
    _GRAMMAR, parser='lalr', propagate_positions=True, keep_all_tokens=True)

_FN_BLACKLIST = set([])

_FN_BLACKLIST_REGEX = [
    # ATEN CUDA functions
    r'[^(]*cudnn',
    r'[^(]*cufft',
    r'[^(]*mkldnn',
]

_FN_DNNL_FUNCS_WITH_SIMPLE_ATEN_SIG = [
    'add(Tensor,Tensor,Scalar)->Tensor',
    'add_(Tensor,Tensor,Scalar)->Tensor',
    'add_out(Tensor,Tensor,Tensor,Scalar)->Tensor',
    'mul(Tensor, Tensor) -> Tensor',
    'mul_(Tensor,Tensor)->Tensor',
    'mul_out(Tensor,Tensor,Tensor)->Tensor',
    'linear(Tensor, Tensor, Tensor) -> Tensor',
    'dropout(Tensor, double, bool) -> Tensor',
    'native_batch_norm(Tensor, Tensor, Tensor, Tensor, Tensor, bool, double, double) -> std::tuple<Tensor,Tensor,Tensor>',
    'native_batch_norm_backward(Tensor, Tensor, Tensor, Tensor, Tensor, Tensor, Tensor, bool, double, std::array<bool,3>) -> std::tuple<Tensor,Tensor,Tensor>',
    'avg_pool2d(Tensor, IntArrayRef, IntArrayRef, IntArrayRef, bool, bool, c10::optional<int64_t>) -> Tensor',
    'avg_pool2d_backward(Tensor, Tensor, IntArrayRef, IntArrayRef, IntArrayRef, bool, bool, c10::optional<int64_t>) -> Tensor',
    'avg_pool3d(Tensor, IntArrayRef, IntArrayRef, IntArrayRef, bool, bool, c10::optional<int64_t>) -> Tensor',
    'avg_pool3d_backward(Tensor, Tensor, IntArrayRef, IntArrayRef, IntArrayRef, bool, bool, c10::optional<int64_t>) -> Tensor',
    'relu(Tensor)->Tensor',
    'relu_(Tensor)->Tensor',
    '_softmax(Tensor, int64_t, bool) -> Tensor',
    '_softmax_backward_data(Tensor, Tensor, int64_t, Tensor) -> Tensor',
    'sigmoid(Tensor) -> Tensor',
    'sigmoid_(Tensor) -> Tensor',
    'sigmoid_backward(Tensor, Tensor) -> Tensor',
    'reshape(Tensor, IntArrayRef) -> Tensor',
    'cat_out(Tensor, TensorList, int64_t) -> Tensor',
    'cat(TensorList, int64_t) -> Tensor',
    'split_with_sizes(Tensor, IntArrayRef, int64_t) -> std::vector<Tensor>',
    'bmm(Tensor, Tensor) -> Tensor',
    'bmm_out(Tensor, Tensor, Tensor) -> Tensor',
    'mm(Tensor, Tensor) -> Tensor',
    'mm_out(Tensor, Tensor, Tensor) -> Tensor',
    'baddbmm(Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'baddbmm_(Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'baddbmm_out(Tensor, Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'addmm(Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'addmm_(Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'addmm_out(Tensor, Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'addbmm(Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'addbmm_(Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
    'addbmm_out(Tensor, Tensor, Tensor, Tensor, Scalar, Scalar) -> Tensor',
]

_FN_WITH_ALIAS_FEATURE = 'Tensor(a)'

_FALLBACK_TO_CPU_TENSOR_LIST = 'fallbackToCPUTensorList'
_FALLBACK_TO_CPU_TENSOR = 'fallbackToCPUTensor'
_UPGRADE_TO_DPCPP_TENSOR = 'upgradeToDPCPPTensor'
_UPGRADE_TO_DPCPP_TENSOR_VEC = 'upgradeToDPCPPTensorVec'
_SHALLOW_FALLBACK_TO_CPU_TENSOR_LIST = 'shallowFallbackToCPUTensorList'
_SHALLOW_FALLBACK_TO_CPU_TENSOR = 'shallowFallbackToCPUTensor'
_SHALLOW_UPGRADE_TO_DPCPP_TENSOR = 'shallowUpgradeToDPCPPTensor'
_SHALLOW_UPGRADE_TO_DPCPP_TENSOR_VEC = 'shallowUpgradeToDPCPPTensorVec'
_SHALLOW_UPGRADE_TO_DPCPP_TENSOR_A = 'shallowUpgradeToDPCPPTensorA'
_SHALLOW_UPGRADE_TO_DPCPP_TENSOR_AW = 'shallowUpgradeToDPCPPTensorAW'

_TYPE_NSMAP = {
    'Tensor': 'at::Tensor',
    'TensorList': 'at::TensorList',
    'Scalar': 'at::Scalar',
    'Storage': 'at::Storage',
    'IntList': 'at::IntList',
    'IntArrayRef': 'at::IntArrayRef',
    'Generator': 'at::Generator',
    'ScalarType': 'at::ScalarType',
    'TensorOptions': 'at::TensorOptions',
    'SparseTensorRef': 'at::SparseTensorRef',
    'Device': 'c10::Device',
    'optional': 'c10::optional',
    'MemoryFormat': 'at::MemoryFormat',
    'QScheme': 'at::QScheme',
    'ConstQuantizerPtr': 'at::ConstQuantizerPtr',
    'Dimname': 'at::Dimname',  # namedtensor-only
    'DimnameList': 'at::DimnameList',  # namedtensor-only
}

_H_HEADER = """// Autogenerated file by {gen}. Do not edit directly!
#pragma once

#include <ATen/Tensor.h>

namespace torch_ipex {{
namespace cpu {{

class AtenIpexCPUDefault {{
 public:
{hfuncs}
}};

}}  // namespace cpu
}}  // namespace torch_ipex
"""

_CPP_HEADER = """// Autogenerated file by {gen}. Do not edit directly!
#include "OPs.h"

#include <ATen/Context.h>
#include <ATen/CPUGenerator.h>
#include <c10/util/Exception.h>
#include <c10/util/Logging.h>

#include "aten_ipex_bridge.h"
#include "utils.h"
#include "DevOPs.h"
#include "dbl/DNNLChecker.h"

namespace torch_ipex {{
namespace cpu {{

{funcs}

}}  // namespace cpu
}}  // namespace torch_ipex
"""

_FUNCTION_OPTIONS = {}

_RESULT_NAME = '_ipex_result'


class Context(object):

    def __init__(self, functions):
        with open(functions, 'r') as ff:
            self.functions_data = ff.read()

    def get_function(self, name):
        if self.functions_data.find(' {}('.format(name)) >= 0:
            return 'at::{}'.format(name)


class StringEmit(object):

    def __init__(self, sref):
        self.sref = sref
        self.sval = ''
        self.pos = -1

    def __repr__(self):
        return self.sval

    def advance(self, t):
        start = t.column - 1
        end = t.end_column - 1
        pos = self.pos if self.pos >= 0 else start
        if start > pos:
            self.sval += self.sref[pos:start]
        self.sval += t.value
        self.pos = end

    def skip(self, t):
        self.pos = last_match(t) if self.pos >= 0 else -1

    def append(self, s):
        self.sval += s
        self.pos = -1


class TensorFetcher(object):

    def __init__(self):
        self.tensors = []
        self.writeable_tensors = []

    def add(self, name, writeable):
        new_tensor_name = '_ipex_{}'.format(name)
        if writeable:
            self.writeable_tensors.append((name, new_tensor_name))
        self.tensors.append(name)
        return new_tensor_name

    def generate_fetches(self):
        ipex_code = ''
        for tensor in self.tensors:
            ipex_code += '  auto&& _ipex_{} = bridge::{}({});\n'.format(tensor, _SHALLOW_FALLBACK_TO_CPU_TENSOR, tensor)
        return ipex_code

    def generate_updates(self):
        ipex_code = ''
        if len(self.writeable_tensors) > 0:
            for (w_tensor_name, w_new_tensor_name) in self.writeable_tensors:
                ipex_code += '  bridge::{}({}, {});\n'.format(_SHALLOW_UPGRADE_TO_DPCPP_TENSOR_AW,
                                                              w_tensor_name,
                                                              w_new_tensor_name)
        return ipex_code


def list_get(l, n):
    return l[n] if n < len(l) else None


def is_blacklisted_fn(fname, mapsig):
    if fname in _FN_BLACKLIST or mapsig in _FN_BLACKLIST:
        return True
    for frx in _FN_BLACKLIST_REGEX:
        if re.match(frx, fname) or re.match(frx, mapsig):
            return True
    return False


def is_write_param(fnopts, pname, defval):
    if fnopts and fnopts.wparams:
        if pname in fnopts.wparams:
            return True
    return defval


def last_match(t):
    if isinstance(t, lark.lexer.Token):
        return t.end_column - 1
    assert isinstance(t, lark.tree.Tree)
    return last_match(t.children[-1])


def for_every_token(t, fn):
    if isinstance(t, lark.lexer.Token):
        fn(t)
    else:
        assert isinstance(t, lark.tree.Tree)
        for c in t.children:
            for_every_token(c, fn)


def emit_string(t, emit, emit_fn):
    status = emit_fn(t)
    if status > 0:

        def do_emit(tok):
            emit.advance(tok)

        for_every_token(t, do_emit)
    elif status == 0:
        if isinstance(t, lark.lexer.Token):
            emit.advance(t)
        else:
            assert isinstance(t, lark.tree.Tree)
            for c in t.children:
                emit_string(c, emit, emit_fn)
    else:
        emit.skip(t)


def typed_child(t, n, ttype):
    assert isinstance(t, lark.tree.Tree)
    assert n < len(t.children)
    c = t.children[n]
    assert isinstance(c, lark.tree.Tree)
    assert c.data == ttype, t.pretty()
    return c


def rewrite_sig(tree, orig_sig, emit_fn=lambda x: 0):
    emit = StringEmit(orig_sig)
    emit_string(tree, emit, emit_fn)
    return str(emit)


def rewrite_signature(sig, tmap):
    def rewrite(t):
        if t.type == 'TNAME':
            new_type = tmap.get(t.value, None)
            if new_type is not None:
                t.value = new_type

    def emit_fn(t):
        if isinstance(t, lark.lexer.Token):
            return 0
        return -1 if t.data == 'param_defval' else 0

    xtree = _XPARSER.parse(sig)
    for_every_token(xtree, rewrite)
    return rewrite_sig(xtree, sig, emit_fn=emit_fn)


def create_stdfunc_sig(tree, orig_sig):
    def emit_fn(t):
        if isinstance(t, lark.lexer.Token):
            return 0
        return -1 if t.data == 'param_name' else 0

    emit = StringEmit(orig_sig)
    # Emit full function return type.
    emit_string(typed_child(tree, 0, 'type'), emit, emit_fn)
    emit.append('(')
    # Emit parameter list w/out parameter names.
    emit_string(typed_child(tree, 3, 'params'), emit, emit_fn)
    emit.append(')')
    return str(emit)


def create_map_sig(tree, orig_sig):
    def emit_fn(t):
        if isinstance(t, lark.lexer.Token):
            return -1 if t.type in ['CONST', 'REF', 'PTR'] else 0
        return -1 if t.data in ['param_name', 'param_defval'] else 0

    emit = StringEmit(orig_sig)
    # Emit full function return type.
    emit_string(typed_child(tree, 1, 'fnname'), emit, emit_fn)
    emit.append('(')
    # Emit parameter list w/out parameter names.
    emit_string(typed_child(tree, 3, 'params'), emit, emit_fn)
    emit.append(') -> ')
    emit_string(typed_child(tree, 0, 'type'), emit, emit_fn)
    return str(emit)


def type_core(t):
    assert isinstance(t, lark.tree.Tree)
    for c in t.children:
        if isinstance(c, lark.tree.Tree) and c.data == 'core_type':
            c = c.children[0]
            if isinstance(c, lark.lexer.Token):
                return c.value
            assert isinstance(c, lark.tree.Tree) and c.data == 'template'
            if c.children[0].value == 'c10::optional':
                type_list = c.children[1]
                assert isinstance(type_list, lark.tree.Tree) and type_list.data == 'typelist'
                return type_core(type_list.children[0])
            return c.children[0].value
    raise RuntimeError('Not a type tree: {}'.format(t))


def type_is_optional(t):
    assert isinstance(t, lark.tree.Tree)
    for c in t.children:
        if isinstance(c, lark.tree.Tree) and c.data == 'core_type':
            c = c.children[0]
            if isinstance(c, lark.lexer.Token):
                return False
            assert isinstance(c, lark.tree.Tree) and c.data == 'template'
            if c.children[0].value == 'c10::optional':
                return True
            else:
                return False
    raise RuntimeError('Not a type tree: {}'.format(t))


def type_is_const(t):
    assert isinstance(t, lark.tree.Tree)
    c = t.children[0]
    return isinstance(c, lark.lexer.Token) and c.value == 'const'


def fn_is_inplace(fname):
    if fname.endswith('_'):
        return True
    else:
        return False


def fn_is_dnnl(simple_aten_sig):
    stripped_str = simple_aten_sig.replace(' ', '')
    for item in _FN_DNNL_FUNCS_WITH_SIMPLE_ATEN_SIG:
        if stripped_str == item.replace(' ', ''):
            return True
    return False


def fn_is_alias(fname):
    if _FN_WITH_ALIAS_FEATURE in fname:
        return True
    else:
        return False


def type_is_refptr(t, kind):
    assert isinstance(t, lark.tree.Tree)
    c = t.children[-1]
    if not isinstance(c, lark.tree.Tree) or c.data != 'refspec':
        return False
    c = c.children[0]
    return isinstance(c, lark.lexer.Token) and c.value == kind


def extract_list(t, l):
    assert isinstance(t, lark.tree.Tree)
    l.append(t.children[0])
    if len(t.children) == 2:
        c = t.children[1]
        if isinstance(c, lark.tree.Tree) and c.data == t.data:
            extract_list(c, l)
    return l


def tuple_type_list(t):
    assert isinstance(t, lark.tree.Tree)
    c = t.children[0]
    assert isinstance(c, lark.tree.Tree) and c.data == 'core_type'
    c = c.children[0]
    assert isinstance(c, lark.tree.Tree) and c.data == 'template'
    types = []
    return extract_list(c.children[1], types)


def get_function_name(t):
    assert isinstance(t, lark.tree.Tree)
    fname = t.children[1]
    assert isinstance(fname, lark.tree.Tree)
    assert fname.data == 'fnname'
    return fname.children[0].value


def get_function_signature(t, orig_sig, namefn):
    emit = StringEmit(orig_sig)
    # Emit full function return type.
    emit_string(typed_child(t, 0, 'type'), emit, lambda t: 0)
    fnname = typed_child(t, 1, 'fnname').children[0]
    xfname = namefn(fnname.value)
    emit.append(' {}('.format(xfname))
    # Emit parameter list w/out parameter names.
    emit_string(typed_child(t, 3, 'params'), emit, lambda t: 0)
    emit.append(')')
    return str(emit), fnname.value, xfname


def get_parameters(t):
    assert isinstance(t, lark.tree.Tree)
    c = t.children[2]
    assert isinstance(c, lark.tree.Tree)
    assert c.data == 'params'
    params = []
    extract_list(c, params)
    return params


def param_name(t):
    assert isinstance(t, lark.tree.Tree)
    c = t.children[1]
    assert isinstance(c, lark.tree.Tree)
    assert c.data == 'param_name'
    token = c.children[0]
    assert isinstance(token, lark.lexer.Token)
    return token.value


def param_type(t):
    assert isinstance(t, lark.tree.Tree)
    c = t.children[0]
    assert isinstance(c, lark.tree.Tree)
    return c


def get_optional(fnopts, name, defval=None):
    if fnopts is None or not hasattr(fnopts, name):
        return defval
    return getattr(fnopts, name, defval) or defval


def get_return_value(rtype, rname, param, var, ref_param, fnopts, fname):
    crtype = type_core(rtype)
    ret_check = ''
    if type_is_const(rtype) or type_is_refptr(rtype, '&'):
        # If the return type is a const or a reference, return the matching
        # parameter. In these cases we operated on IPEX tensors data (the ATEN one),
        # but the returned references are the input parameters.
        assert param
        return ret_check, param_name(param)
    elif crtype != 'Tensor':
        return ret_check, rname
    else:
        # If instead the return type is a value Tensor, we create a new one by
        # wrapping the proper local variable which has been created by calling
        # into the CPU tensor implementation.
        if fn_is_inplace(fname):
            # Conver at::Tensor AtenIpexCPUDefault::__xxx__(const at::Tensor & xxx, ...) {
            ptype = param_type(param)
            if type_is_const(ptype):
                # ret_check += '  TORCH_INTERNAL_ASSERT({}.is_contiguous());\n'.format(rname)
                return ret_check, 'bridge::{}({})'.format(_SHALLOW_UPGRADE_TO_DPCPP_TENSOR, rname)
            else:
                assert False
        else:
            # ret_check += '  TORCH_INTERNAL_ASSERT({}.is_contiguous());\n'.format(rname)
            return ret_check, 'bridge::{}({})'.format(_SHALLOW_UPGRADE_TO_DPCPP_TENSOR, rname)


def get_reference_param(params, fnopts=None):
    # The reference parameter is the Tensor object which we use to extract the
    # result Tensor device, if any.
    ref_param = None
    other = None
    for p in params:
        ptype = param_type(p)
        cptype = type_core(ptype)
        pname = param_name(p)
        if get_optional(fnopts, 'ref_param') == pname:
            return p
        if not other and (cptype == 'TensorOptions' or cptype == 'TensorList'):
            other = p
        if cptype != 'Tensor':
            continue
        if not ref_param and (pname == 'self' or type_is_const(ptype)):
            ref_param = p
        other = p
    return ref_param or other


def get_tuple_return(rtype, rtype_str, rname, params, param_vars, ref_param, fnopts, fname):
    types = tuple_type_list(rtype)
    ret_check_str = ''
    ret_str = '{}('.format(rtype_str)
    for i, ttype in enumerate(types):
        if i > 0:
            ret_str += ', '
        tuple_var = 'std::get<{}>({})'.format(i, rname)
        ret_check, ret = get_return_value(ttype,
                                          tuple_var,
                                          list_get(params, i),
                                          list_get(param_vars, i),
                                          ref_param,
                                          fnopts,
                                          fname)
        ret_str += ret
        ret_check_str += ret_check
    ret_str += ')'
    return ret_check_str, ret_str


def get_return_type_str(t, orig_sig):
    assert isinstance(t, lark.tree.Tree)
    fname = t.children[1]
    assert isinstance(fname, lark.tree.Tree)
    assert fname.data == 'fnname'
    token = fname.children[0]
    assert isinstance(token, lark.lexer.Token)
    return orig_sig[0:token.column - 2]


def generate_return_stmt(t, rtype_str, fname, rname, params, param_vars, ref_param, fnopts):
    assert isinstance(t, lark.tree.Tree)
    rtype = t.children[0]
    ctype = type_core(rtype)
    post_check = ''
    if ctype == 'std::tuple':
        assert not fn_is_inplace(fname)
        ret_check_str, retstr = get_tuple_return(rtype,
                                                 rtype_str,
                                                 rname,
                                                 params,
                                                 param_vars,
                                                 ref_param,
                                                 fnopts,
                                                 fname)
        post_check += ret_check_str
    elif ctype == 'std::vector':
        assert not fn_is_inplace(fname)
        retstr = 'bridge::{}({})'.format(_SHALLOW_UPGRADE_TO_DPCPP_TENSOR_VEC, rname)
    elif ctype == 'Tensor':
        ret_check_str, retstr = get_return_value(rtype,
                                                 rname,
                                                 params[0],
                                                 param_vars[0],
                                                 ref_param,
                                                 fnopts,
                                                 fname)
        post_check += ret_check_str
    elif ctype == 'void' and not type_is_refptr(rtype, '*'):
        return ''
    else:
        retstr = rname
    return post_check + '  return {};\n'.format(retstr)


def generate_result_assignment(t, rname):
    assert isinstance(t, lark.tree.Tree)
    rtype = t.children[0]
    ctype = type_core(rtype)
    if ctype == 'void' and not type_is_refptr(rtype, '*'):
        return ''
    return 'auto&& {} = '.format(rname)


def get_handling_function(ctx, fname, ipex_ref_param, param_vars):
    function = ctx.get_function(fname)
    if function:
        code = '{}({})'.format(function, ', '.join(param_vars))
    else:
        other_params = list(param_vars)
        other_params.remove(ipex_ref_param)
        code = '{}.{}({})'.format(ipex_ref_param, fname, ', '.join(other_params))
    return code


def get_dnnl_dispatch_function(fname, is_inplace, param_vars, dnnl_tensor_param_vars):
    code = ''

    def is_out_func(fname):
        return fname.endswith("_out")

    code += '\n  if (check_auto_dnnl()) {\n'
    code += '    std::vector<at::Tensor> dnnl_input_tensors;\n'
    if len(dnnl_tensor_param_vars) > 0:
        for dnnl_tensor_param_var in dnnl_tensor_param_vars:
            code += '    dnnl_input_tensors.push_back({});\n'.format(dnnl_tensor_param_var)

    if is_inplace:
        assert len(dnnl_tensor_param_vars) > 0
        code += '    if (dbl::chk::dnnl_inplace_support_the_tensors(dnnl_input_tensors))\n'
        code += '      return AtenIpexCPUDev::dil_{}({});\n'.format(fname, ', '.join(list(param_vars)))
    else:
        param_seq_str_vec = []
        for param_var in param_vars:
            param_seq_str = param_var
            if param_var in dnnl_tensor_param_vars:
                if param_var == 'out' and is_out_func(fname):
                    code += '    TORCH_INTERNAL_ASSERT({}.is_contiguous());\n'.format(param_var)
                else:
                    param_seq_str = '{}.is_contiguous() ? {} : {}.contiguous()'.format(param_var, param_var, param_var)
            param_seq_str_vec.append(param_seq_str)
        code += '    if (dbl::chk::dnnl_support_the_tensors(dnnl_input_tensors))\n'
        code += '      return AtenIpexCPUDev::dil_{}({});\n'.format(fname, ', '.join(param_seq_str_vec))

    code += '  }\n\n'

    return code


def rewrite_tensor_options(fname, pname):
    xname = '_ipex_{}'.format(pname)
    check_cond = '{}.device().type() == at::DeviceType::DPCPP'.format(pname)
    code = '  TORCH_INTERNAL_ASSERT({});\n'.format(check_cond)
    code += '  at::TensorOptions {} = {}.device(at::DeviceType::CPU);\n'.format(xname, pname)
    return code, xname


def generate_aten_to_ipex(ctx, tree, mapsig, rwxtree, fname, sig, rwsig, params, fnopts):
    ref_param = get_reference_param(params, fnopts=fnopts)

    code = '{} {{\n'.format(sig)
    #code += '  printf("AtenIpexCPUDefault::{}\\n");\n'.format(fname)
    ipex_ref_param = param_name(ref_param) if ref_param else None
    tfetcher = TensorFetcher()
    param_vars = []
    dnnl_op_input_tensor_vars = []
    dnnl_op_input_vars = []
    is_inplace = fn_is_inplace(fname)
    is_dnnl = fn_is_dnnl(mapsig)
    for p in params:
        ptype = param_type(p)
        cptype = type_core(ptype)
        pname = param_name(p)
        if cptype == 'TensorList':
            xname = '_ipex_{}'.format(pname)
            code += ('  auto&& {} = bridge::{}({});\n').format(xname, _SHALLOW_FALLBACK_TO_CPU_TENSOR_LIST, pname)
            param_vars.append(xname)
            dnnl_op_input_vars.append(pname)
        elif cptype == 'TensorOptions':
            gcode, xname = rewrite_tensor_options(fname, pname)
            code += gcode
            param_vars.append(xname)
            dnnl_op_input_vars.append(pname)
        elif cptype == 'Storage':
            code += '  TORCH_INTERNAL_ASSERT({}.device_type() == c10::DeviceType::DPCPP);\n'.format(pname)
            param_vars.append(pname)
            dnnl_op_input_vars.append(pname)
        elif cptype == 'MemoryFormat':
            if type_is_optional(ptype):
                check_cond = '{}.value_or(c10::MemoryFormat::Contiguous) != c10::MemoryFormat::Contiguous'.format(pname)
            else:
                check_cond = '{} != c10::MemoryFormat::Contiguous'.format(pname)
            code += '  if ({})\n'.format(check_cond)
            code += '      TORCH_WARN({});\n'.format(check_cond)
            param_vars.append(pname)
            dnnl_op_input_vars.append(pname)
        elif cptype != 'Tensor':
            param_vars.append(pname)
            dnnl_op_input_vars.append(pname)

        # Tensor
        else:
            assert cptype == 'Tensor'
            check_cond = '{}.layout() == c10::kStrided'.format(pname)
            code += '  TORCH_INTERNAL_ASSERT({});\n'.format(check_cond)
            if type_is_const(ptype):
                defval = is_write_param(fnopts, pname, False)
            else:
                defval = is_write_param(fnopts, pname, True)
            xname = tfetcher.add(pname, defval)
            param_vars.append(xname)
            dnnl_op_input_vars.append(pname)

            # If current OP can be routed to DNNL and it is with in-place semantic.
            # We need to check if input tensors match DNNL requirements.
            if is_dnnl:
                dnnl_op_input_tensor_vars.append(pname)

        if p == ref_param and not get_optional(fnopts, 'ref_param'):
            ipex_ref_param = param_vars[-1]

    if is_dnnl:
        code +=  get_dnnl_dispatch_function(fname, is_inplace, dnnl_op_input_vars, dnnl_op_input_tensor_vars)

    code += tfetcher.generate_fetches()
    result_assign = generate_result_assignment(tree, _RESULT_NAME)
    code += '  {}{};\n'.format(
        result_assign,
        get_handling_function(ctx, fname, ipex_ref_param, param_vars))
    code += tfetcher.generate_updates()
    if result_assign:
        code += ('  static_cast<void>({}); // Avoid warnings in case not used\n'.format(_RESULT_NAME))
    code += generate_return_stmt(tree,
                                 get_return_type_str(rwxtree, rwsig),
                                 fname,
                                 _RESULT_NAME if result_assign else None, params,
                                 param_vars,
                                 ref_param,
                                 fnopts)
    code += '}'
    return code


def get_ipex_wrapper(fndef, ctx):
    tree = _PARSER.parse(fndef.cpp_sig)
    xtree = _XPARSER.parse(fndef.cpp_sig)
    mapsig = create_map_sig(xtree, fndef.cpp_sig)
    rwsig = rewrite_signature(fndef.cpp_sig, _TYPE_NSMAP)
    rwxtree = _XPARSER.parse(rwsig)
    params = get_parameters(tree)
    fnopts = _FUNCTION_OPTIONS.get(mapsig, None)

    if fn_is_alias(fndef.aten_sig):
        return None

    def gen_fnname(x):
        return 'AtenIpexCPUDefault::{}'.format(x)

    sig, fname, xfname = get_function_signature(rwxtree, rwsig, gen_fnname)
    if not is_blacklisted_fn(fname, mapsig):
        code = generate_aten_to_ipex(ctx, tree, mapsig, rwxtree, fname, sig, rwsig, params, fnopts)
    else:
        code = None
    return FuncGen(
        tree=tree,
        xtree=xtree,
        rwxtree=rwxtree,
        func=fname,
        xfunc=xfname,
        code=code,
        sig=fndef.cpp_sig,
        rwsig=rwsig,
        cppsig=sig,
        mapsig=mapsig,
        funsig=create_stdfunc_sig(rwxtree, rwsig),
        aten_sig=fndef.aten_sig)


def is_tensor_api(fndef):
    fndef = fndef.replace('at::', '')
    fndef = fndef.replace('c10::Device', 'Device')
    m = re.search(r'\bTensor\b', fndef)
    return m is not None, fndef


def extract_functions(path):
    functions = []
    errors = []
    for line in open(path, 'r'):
        m = re.match(r'\s*([^\s].*); //\s+(.*)', line)
        if not m:
            continue
        fndef = m.group(1)
        try:
            _XPARSER.parse(fndef)
            functions.append(FuncDef(cpp_sig=fndef, aten_sig=m.group(2)))
        except Exception as e:
            if is_tensor_api(fndef)[0]:
                errors.append((fndef, str(e)))
                print('Error parsing "{}": {}'.format(fndef, e), file=sys.stderr)
    return functions, errors


def get_mapsig_key(mapsig):
    # PyTorch generates std::tuple<> without space among the tuple types,
    # which would require special understanding in the string rewriter.
    # Since we are using this as simple key, we can just string the spaces.
    return mapsig.replace(' ', '')


def parse_local_overrides(path):
    functions = []
    fndef = None
    for line in open(path, 'r'):
        line = line.strip()
        if not fndef:
            m = re.match(r'static\s+(.*);', line)
            if m:
                functions.append(m.group(1))
                continue
            m = re.match(r'static\s+(.*)', line)
            if m:
                fndef = m.group(1)
        else:
            fndef = '{} {}'.format(fndef, line)
            if fndef.endswith(';'):
                functions.append(fndef[:-1])
                fndef = None
    assert fndef is None

    overrides = {}
    for fndef in functions:
        # Discard static IPEX type functions which are not ATEN.
        is_tensor, fndef = is_tensor_api(fndef)
        if is_tensor:
            xtree = _XPARSER.parse(fndef)
            mapsig_key = get_mapsig_key(create_map_sig(xtree, fndef))
            overrides[mapsig_key] = fndef
    return overrides


def get_overridden_fns(fgens, overrides):
    overridden = set()
    for fgen in fgens:
        mapsig_key = get_mapsig_key(fgen.mapsig)
        if mapsig_key in overrides:
            overridden.add(mapsig_key)
    return overridden


def generate_functions(fgens):
    code = ''
    for fgen in fgens:
        if fgen.code:
            code += '{}\n\n'.format(fgen.code)
    return code


def generate_class_functions(fgens):
    code = ''
    for fgen in fgens:
        if fgen.code:
            code += '  static {};\n'.format(fgen.rwsig)
    return code


def gen_output_file(args, name):
    if not args.output_folder:
        return sys.stdout
    return open(os.path.join(args.output_folder, name), 'w')


def gen_h_output_file(args):
    return gen_output_file(args, 'OPs.h')


def gen_cpp_output_file(args):
    return gen_output_file(args, 'OPs.cpp')


def check_overrides(overrides, overridden):
    misses = 0
    for mapsig, cpp_sig in overrides.items():
        mapsig_key = get_mapsig_key(mapsig)
        if not mapsig_key in overridden:
            misses += 1
            print('IPEX function missed override: {}; // {}'.format(cpp_sig, mapsig), file=sys.stderr)
    return misses == 0


def generate(args):
    # Parse all PyTorch exposed functions
    fndefs, errors = extract_functions(args.typedef)
    print(
        'Extracted {} functions ({} errors) from {}'.format(
            len(fndefs), len(errors), args.typedef),
        file=sys.stderr)
    assert len(errors) == 0

    overrides = parse_local_overrides(args.ipex_cpu_type)
    print(
        '{} function overrides in {}'.format(len(overrides), args.ipex_cpu_type),
        file=sys.stderr)

    fgens = []
    ctx = Context(args.functions)
    for ts in fndefs:
        fgen = get_ipex_wrapper(ts, ctx)
        if fgen:
            fgens.append(fgen)
    print(
        'Generated {} wrappers for {}'.format(len(fgens), args.typedef),
        file=sys.stderr)

    functions = generate_functions(fgens)
    hfunctions = generate_class_functions(fgens)
    overridden = get_overridden_fns(fgens, overrides)
    # assert check_overrides(overrides, overridden)
    check_overrides(overrides, overridden)
    # Create output files ...
    print(
        _H_HEADER.format(gen=os.path.basename(sys.argv[0]), hfuncs=hfunctions),
        file=gen_h_output_file(args))
    print(
        _CPP_HEADER.format(
            gen=os.path.basename(sys.argv[0]), funcs=functions),
        file=gen_cpp_output_file(args))


if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--output_folder', type=str)
    arg_parser.add_argument(
        'ipex_cpu_type',
        type=str,
        metavar='IPEX_CPU_TYPE_FILE',
        help='The path to the IPEX cpu ATEN overrides file')
    arg_parser.add_argument(
        'typedef',
        type=str,
        metavar='TYPE_DEFAULT_FILE',
        help='The path to the TypeDefault.h file')
    arg_parser.add_argument(
        'functions',
        type=str,
        metavar='FUNCTIONS_FILE',
        help='The path to the Functions.h file')
    args, files = arg_parser.parse_known_args()
    print(args)
    print(files)
    generate(args)
