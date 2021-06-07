#pragma once

#include <ATen/ATen.h>
#include <ATen/Functions.h>
#include <ATen/TensorUtils.h>
#include <ATen/core/Reduction.h>

#include "comm/ApplyUtils.h"
#include <utils/DPCPP.h>
#include <utils/DPCPPUtils.h>
#include <core/Memory.h>
#include <core/TensorImplUtils.h>

using namespace at;
using namespace DPCPP;
using namespace xpu::dpcpp;

static inline void col2im_shape_check(
    const Tensor& input,
    const Tensor& grad_output,
    int64_t output_height,
    int64_t output_width,
    int64_t kernel_height,
    int64_t kernel_width,
    int64_t dilation_height,
    int64_t dilation_width,
    int64_t pad_height,
    int64_t pad_width,
    int64_t stride_height,
    int64_t stride_width) {
  TORCH_CHECK(
      kernel_width > 0 && kernel_height > 0,
      "kernel size should be greater than zero, but got kernel_height: ",
      kernel_height,
      " kernel_width: ",
      kernel_width);
  TORCH_CHECK(
      stride_width > 0 && stride_height > 0,
      "stride should be greater than zero, but got stride_height: ",
      stride_height,
      " stride_width: ",
      stride_width);
  TORCH_CHECK(
      dilation_width > 0 && dilation_height > 0,
      "dilation should be greater than zero, but got dilation_height: ",
      dilation_height,
      " dilation_width: ",
      dilation_width);

  int64_t ndim = input.ndimension();
  TORCH_CHECK(
      input.numel() != 0 && (ndim == 2 || ndim == 3),
      "Expected non-empty 2D or 3D input tensor, but got input of sizes",
      input.sizes());

  int64_t batch_dim = (ndim == 3) ? 0 : -1;
  int64_t n_input_plane = input.size(batch_dim + 1);

  if (n_input_plane % (kernel_width * kernel_height) != 0) {
    AT_ERROR(
        "Expected size of input's dimension 1 to be divisible by the "
        "product of kernel_size, but got input.size(1)=",
        n_input_plane,
        " and kernel_size=(",
        kernel_height,
        ", ",
        kernel_width,
        ").");
  }

  int64_t input_length = input.size(batch_dim + 2);
  int64_t n_blocks_height = div_rtn<int64_t>(
                                output_height + 2 * pad_height -
                                    dilation_height * (kernel_height - 1) - 1,
                                stride_height) +
      1;
  int64_t n_blocks_width = div_rtn<int64_t>(
                               output_width + 2 * pad_width -
                                   dilation_width * (kernel_width - 1) - 1,
                               stride_width) +
      1;

  if (input_length != (n_blocks_height * n_blocks_width)) {
    AT_ERROR(
        "Given output_size=(",
        output_height,
        ", ",
        output_width,
        "), kernel_size=(",
        kernel_height,
        ", ",
        kernel_width,
        "), dilation=(",
        dilation_height,
        ", ",
        dilation_width,
        "), padding=(",
        pad_height,
        ", ",
        pad_width,
        "), stride=(",
        stride_height,
        ", ",
        stride_width,
        "), expected size of input's dimension 2 to match the calculated "
        "number of ",
        "sliding blocks ",
        n_blocks_height,
        " * ",
        n_blocks_width,
        " = ",
        (n_blocks_height * n_blocks_width),
        ", but got input.size(2)=",
        input_length,
        ".");
  }

  if (output_width < 1 || output_height < 1) {
    AT_ERROR(
        "Expected output spatial size to be positive, but got: output_size=(",
        output_height,
        ", ",
        output_width,
        ").");
  }
}

static inline void im2col_shape_check(
    const Tensor& input,
    const Tensor& grad_output,
    int64_t kernel_height,
    int64_t kernel_width,
    int64_t dilation_height,
    int64_t dilation_width,
    int64_t pad_height,
    int64_t pad_width,
    int64_t stride_height,
    int64_t stride_width) {
  TORCH_CHECK(
      kernel_width > 0 && kernel_height > 0,
      "kernel size should be greater than zero, but got kernel_height: ",
      kernel_height,
      " kernel_width: ",
      kernel_width);

  TORCH_CHECK(
      dilation_width > 0 && dilation_height > 0,
      "dilation should be greater than zero, but got dilation_height: ",
      dilation_height,
      " dilation_width: ",
      dilation_width);

  TORCH_CHECK(
      pad_width >= 0 && pad_height >= 0,
      "padding should be non-negative, but got pad_height: ",
      pad_height,
      " pad_width: ",
      pad_width);

  TORCH_CHECK(
      stride_width > 0 && stride_height > 0,
      "stride should be greater than zero, but got stride_height: ",
      stride_height,
      " stride_width: ",
      stride_width);

  int64_t ndim = input.ndimension();

  TORCH_CHECK(
      input.numel() != 0 && (ndim == 3 || ndim == 4),
      "Expected non-empty 3D or 4D input tensor, but got input of size ",
      input.sizes());

  int64_t dim_batch = 0;

  if (ndim == 3) {
    dim_batch = -1;
  }

  int64_t input_height = input.size(dim_batch + 2);
  int64_t input_width = input.size(dim_batch + 3);
  int64_t output_height = div_rtn<int64_t>(
                              input_height + 2 * pad_height -
                                  (dilation_height * (kernel_height - 1) + 1),
                              stride_height) +
      1;
  int64_t output_width = div_rtn<int64_t>(
                             input_width + 2 * pad_width -
                                 (dilation_width * (kernel_width - 1) + 1),
                             stride_width) +
      1;

  if (output_height < 1 || output_width < 1) {
    AT_ERROR(
        "Given input with spatial size (",
        input_height,
        ", ",
        input_height,
        "), kernel_size=(",
        kernel_height,
        ", ",
        kernel_width,
        "), dilation=(",
        dilation_height,
        ", ",
        dilation_width,
        "), padding=(",
        pad_height,
        ", ",
        pad_width,
        "), calculated shape of the array of sliding blocks as (",
        output_height,
        ", ",
        output_width,
        "), which is too small (non-positive).");
  }
}
