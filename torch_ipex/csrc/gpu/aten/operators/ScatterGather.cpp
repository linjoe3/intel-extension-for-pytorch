#include <ATen/ATen.h>

#include <core/DPCPP.h>
#include <core/TensorImplUtils.h>
#include <core/detail/IndexUtils.h>
#include <core/detail/TensorInfo.h>

#include <utils/General.h>

#include "ScatterGather.h"

using namespace at::dpcpp::detail;
using namespace at::dpcpp;

namespace at {
namespace AtenIpexTypeDPCPP {
namespace impl {

#define RUN(TYPE, DIMS, REAL)                   \
  THDPCPPTensor_gatherKernel<TYPE, REAL, DIMS>( \
      tensorInfo, srcInfo, indexInfo, dim, (TYPE)totalElements);

template <typename scalar_t>
void Gather(
    Tensor& tensor,
    const Tensor& src,
    int64_t dim,
    const Tensor& index) {
  TORCH_CHECK(
      TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(index)) ==
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(src)),
      "Index tensor must have same dimensions as input tensor");
  TORCH_CHECK(
      TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(index)) ==
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Index tensor must have same dimensions as output tensor");
  TORCH_CHECK(
      dim >= 0 &&
          dim < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Index dimension is out of bounds");
  TORCH_CHECK(
      TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(src)) ==
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Input tensor must have same dimensions as output tensor");

  for (int d = 0;
       d < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor));
       d++) {
    if (d != dim) {
      TORCH_CHECK(
          TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(tensor), d) ==
              TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(src), d),
          "Input tensor must have same size as output tensor apart from the "
          "specified dimension");
    }
  }

  TORCH_CHECK(
      TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)) <=
          MAX_DPCPPTORCH_DIMS,
      DPCPPTORCH_DIM_WARNING);

  const ptrdiff_t totalElements = index.numel();

  Tensor oldTensor;
  if (maybeOverlappingIndices(tensor)) {
    oldTensor = tensor;
    tensor = tensor.contiguous();
  }

  if (totalElements > 0) {
    if (canUse32BitIndexMath(tensor) && canUse32BitIndexMath(src) &&
        canUse32BitIndexMath(index)) {
      TensorInfo<scalar_t, unsigned int> tensorInfo =
          getTensorInfo<scalar_t, unsigned int>(tensor);
      TensorInfo<scalar_t, unsigned int> srcInfo =
          getTensorInfo<scalar_t, unsigned int>(src);
      TensorInfo<int64_t, unsigned int> indexInfo =
          getTensorInfo<int64_t, unsigned int>(index);
      // Specialize for a small number of dimensions.
      switch (indexInfo.dims) {
        case 1:
          RUN(unsigned int, 1, scalar_t);
          break;
        case 2:
          RUN(unsigned int, 2, scalar_t);
          break;
        case 3:
          RUN(unsigned int, 3, scalar_t);
          break;
        default:
          RUN(unsigned int, -1, scalar_t);
          break;
      }
    } else {
      TensorInfo<scalar_t, uint64_t> tensorInfo =
          getTensorInfo<scalar_t, uint64_t>(tensor);
      TensorInfo<scalar_t, uint64_t> srcInfo =
          getTensorInfo<scalar_t, uint64_t>(src);
      TensorInfo<int64_t, uint64_t> indexInfo =
          getTensorInfo<int64_t, uint64_t>(index);

      RUN(uint64_t, -1, scalar_t)
    }
  }

  if (oldTensor.defined()) {
    oldTensor.copy_(tensor);
    // TODO:copyIgnoringOverlaps Called when we are copying into an overlapping
    // index `dst`
  }
}

#undef RUN

#define RUN(TYPE, DIMS, REAL)                   \
  THSyclTensor_scatterKernel<TYPE, REAL, DIMS>( \
      tensorInfo, srcInfo, indexInfo, dim, (TYPE)totalElements);

template <typename scalar_t>
void Scatter(
    Tensor& tensor,
    int64_t dim,
    const Tensor& index,
    const Tensor& src) {
  int index_ndim_legacy_all =
      TensorImpl_nDimensionLegacyAll(TensorImpl_Unwrap(index));
  TORCH_CHECK(
      dim >= 0 &&
          dim < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Index dimension is out of bounds");
  TORCH_CHECK(
      index_ndim_legacy_all == 0 ||
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(index)) ==
              TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(src)),
      "Index tensor must be either empty or have same dimensions as input "
      "tensor");
  TORCH_CHECK(
      TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(src)) ==
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Input tensor must have same dimensions as output tensor");

  // no-op if index is empty
  if (index_ndim_legacy_all == 0)
    return;

  for (int d = 0;
       d < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor));
       d++) {
    int64_t indexSizeD =
        TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(index), d);
    if (d != dim) {
      TORCH_CHECK(
          indexSizeD <=
              TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(tensor), d),
          "Index tensor must not have larger size than output tensor "
          "apart from the specified dimension ",
          dim,
          ", but got index ",
          index.sizes(),
          " output ",
          tensor.sizes());
    }
    TORCH_CHECK(
        indexSizeD <= TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(src), d),
        "Index tensor must not have larger size than input tensor, but "
        "got index ",
        index.sizes(),
        "input",
        src.sizes());
  }

  TORCH_CHECK(tensor.dim() <= MAX_DPCPPTORCH_DIMS, DPCPPTORCH_DIM_WARNING);

  const ptrdiff_t totalElements = index.numel();

  Tensor oldTensor;
  if (maybeOverlappingIndices(tensor)) {
    oldTensor = tensor;
    tensor = tensor.contiguous();
  }

  if (totalElements > 0) {
    if (canUse32BitIndexMath(tensor) && canUse32BitIndexMath(src) &&
        canUse32BitIndexMath(index)) {
      TensorInfo<scalar_t, unsigned int> tensorInfo =
          getTensorInfo<scalar_t, unsigned int>(tensor);
      TensorInfo<scalar_t, unsigned int> srcInfo =
          getTensorInfo<scalar_t, unsigned int>(src);
      TensorInfo<int64_t, unsigned int> indexInfo =
          getTensorInfo<int64_t, unsigned int>(index);
      // Specialize for a small number of dimensions.
      switch (indexInfo.dims) {
        case 1:
          RUN(unsigned int, 1, scalar_t);
          break;
        case 2:
          RUN(unsigned int, 2, scalar_t);
          break;
        case 3:
          RUN(unsigned int, 3, scalar_t);
          break;
        default:
          RUN(unsigned int, -1, scalar_t);
          break;
      }
    } else {
      TensorInfo<scalar_t, uint64_t> tensorInfo =
          getTensorInfo<scalar_t, uint64_t>(tensor);
      TensorInfo<scalar_t, uint64_t> srcInfo =
          getTensorInfo<scalar_t, uint64_t>(src);
      TensorInfo<int64_t, uint64_t> indexInfo =
          getTensorInfo<int64_t, uint64_t>(index);

      RUN(uint64_t, -1, scalar_t)
    }
  }

  if (oldTensor.defined()) {
    oldTensor.copy_(tensor);
    // TODO:copyIgnoringOverlaps Called when we are copying into an overlapping
    // index `dst`
  }
}

#undef RUN

#define RUN(TYPE, DIMS, REAL)                       \
  THSyclTensor_scatterFillKernel<TYPE, REAL, DIMS>( \
      tensorInfo, indexInfo, value, dim, (TYPE)totalElements);

template <typename scalar_t>
void ScatterFill(
    Tensor& tensor,
    int64_t dim,
    const Tensor& index,
    Scalar value_scalar) {
  int index_ndim_legacy_all =
      TensorImpl_nDimensionLegacyAll(TensorImpl_Unwrap(index));
  TORCH_CHECK(
      dim >= 0 &&
          dim < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Index dimension is out of bounds");
  TORCH_CHECK(
      index_ndim_legacy_all == 0 ||
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(index)) ==
              TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Index tensor must be either empty or have same dimensions as output "
      "tensor");

  auto value = value_scalar.to<scalar_t>();
  // no-op if index is empty
  if (index_ndim_legacy_all == 0)
    return;

  for (int d = 0;
       d < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor));
       d++) {
    int64_t indexSizeD =
        TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(index), d);
    if (d != dim) {
      TORCH_CHECK(
          indexSizeD <=
              TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(tensor), d),
          "Index tensor must not have larger size than output tensor "
          "apart from the specified dimension ",
          dim,
          ", but got index ",
          index.sizes(),
          " output ",
          tensor.sizes());
    }
  }

  TORCH_CHECK(tensor.dim() <= MAX_DPCPPTORCH_DIMS, DPCPPTORCH_DIM_WARNING);

  const ptrdiff_t totalElements = index.numel();

  Tensor oldTensor;
  if (maybeOverlappingIndices(tensor)) {
    oldTensor = tensor;
    tensor = tensor.contiguous();
  }

  if (canUse32BitIndexMath(tensor) && canUse32BitIndexMath(index)) {
    TensorInfo<scalar_t, unsigned int> tensorInfo =
        getTensorInfo<scalar_t, unsigned int>(tensor);
    TensorInfo<int64_t, unsigned int> indexInfo =
        getTensorInfo<int64_t, unsigned int>(index);

    // Specialize for a small number of dimensions.
    switch (indexInfo.dims) {
      case 1:
        RUN(unsigned int, 1, scalar_t);
        break;
      case 2:
        RUN(unsigned int, 2, scalar_t);
        break;
      case 3:
        RUN(unsigned int, 3, scalar_t);
        break;
      default:
        RUN(unsigned int, -1, scalar_t);
        break;
    }
  } else {
    TensorInfo<scalar_t, uint64_t> tensorInfo =
        getTensorInfo<scalar_t, uint64_t>(tensor);
    TensorInfo<int64_t, uint64_t> indexInfo =
        getTensorInfo<int64_t, uint64_t>(index);

    RUN(uint64_t, -1, scalar_t);
  }

  if (oldTensor.defined()) {
    oldTensor.copy_(tensor);
    // TODO:copyIgnoringOverlaps Called when we are copying into an overlapping
    // index `dst`
  }
}

#undef RUN

#define RUN(TYPE, DIMS, REAL)                      \
  THSyclTensor_scatterAddKernel<TYPE, REAL, DIMS>( \
      tensorInfo, srcInfo, indexInfo, dim, (TYPE)totalElements);

template <typename scalar_t>
typename std::enable_if<IS_FLOAT32(scalar_t) || IS_INT(scalar_t), void>::type
ScatterAdd(
    Tensor& tensor,
    int64_t dim,
    const Tensor& index,
    const Tensor& src) {
  int index_ndim_legacy_all =
      TensorImpl_nDimensionLegacyAll(TensorImpl_Unwrap(index));
  TORCH_CHECK(
      dim >= 0 &&
          dim < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Index dimension is out of bounds");
  TORCH_CHECK(
      index_ndim_legacy_all == 0 ||
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(index)) ==
              TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(src)),
      "Index tensor must be either empty or have same dimensions as input "
      "tensor");
  TORCH_CHECK(
      TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(src)) ==
          TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor)),
      "Input tensor must have same dimensions as output tensor");

  // no-op if index is empty
  if (index_ndim_legacy_all == 0)
    return;

  for (int d = 0;
       d < TensorImpl_nDimensionLegacyNoScalars(TensorImpl_Unwrap(tensor));
       d++) {
    int64_t indexSizeD =
        TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(index), d);
    if (d != dim) {
      TORCH_CHECK(
          indexSizeD <=
              TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(tensor), d),
          "Index tensor must not have larger size than output tensor "
          "apart from the specified dimension ",
          dim,
          ", but got index ",
          index.sizes(),
          " output ",
          tensor.sizes());
    }
    TORCH_CHECK(
        indexSizeD <= TensorImpl_sizeLegacyNoScalars(TensorImpl_Unwrap(src), d),
        "Index tensor must not have larger size than input tensor, but "
        "got index ",
        index.sizes(),
        "input",
        src.sizes());
  }

  TORCH_CHECK(tensor.dim() <= MAX_DPCPPTORCH_DIMS, DPCPPTORCH_DIM_WARNING);

  const ptrdiff_t totalElements = index.numel();

  Tensor oldTensor;
  if (maybeOverlappingIndices(tensor)) {
    oldTensor = tensor;
    tensor = tensor.contiguous();
  }

  if (totalElements > 0) {
    if (canUse32BitIndexMath(tensor) && canUse32BitIndexMath(src) &&
        canUse32BitIndexMath(index)) {
      TensorInfo<scalar_t, unsigned int> tensorInfo =
          getTensorInfo<scalar_t, unsigned int>(tensor);
      TensorInfo<scalar_t, unsigned int> srcInfo =
          getTensorInfo<scalar_t, unsigned int>(src);
      TensorInfo<int64_t, unsigned int> indexInfo =
          getTensorInfo<int64_t, unsigned int>(index);
      // Specialize for a small number of dimensions.
      switch (indexInfo.dims) {
        case 1:
          RUN(unsigned int, 1, scalar_t);
          break;
        case 2:
          RUN(unsigned int, 2, scalar_t);
          break;
        case 3:
          RUN(unsigned int, 3, scalar_t);
          break;
        default:
          RUN(unsigned int, -1, scalar_t);
          break;
      }
    } else {
      TensorInfo<scalar_t, uint64_t> tensorInfo =
          getTensorInfo<scalar_t, uint64_t>(tensor);
      TensorInfo<scalar_t, uint64_t> srcInfo =
          getTensorInfo<scalar_t, uint64_t>(src);
      TensorInfo<int64_t, uint64_t> indexInfo =
          getTensorInfo<int64_t, uint64_t>(index);

      RUN(uint64_t, -1, scalar_t)
    }
  }

  if (oldTensor.defined()) {
    oldTensor.copy_(tensor);
    // TODO:copyIgnoringOverlaps Called when we are copying into an overlapping
    // index `dst`
  }
}

template <typename scalar_t>
typename std::enable_if<!(IS_FLOAT32(scalar_t) || IS_INT(scalar_t)), void>::type
ScatterAdd(
    Tensor& tensor,
    int64_t dim,
    const Tensor& index,
    const Tensor& src) {
  TORCH_CHECK("scatter add only supports float and int type");
}

#undef RUN

} // namespace impl

Tensor& scatter_(
    Tensor& self,
    int64_t dim,
    const Tensor& index,
    const Tensor& src) {
  AT_DISPATCH_ALL_TYPES_AND(
      at::ScalarType::Bool, self.scalar_type(), "Scatter", [&]() {
        impl::Scatter<scalar_t>(self, dim, index, src);
      });
  return self;
}

Tensor& scatter_(Tensor& self, int64_t dim, const Tensor& index, Scalar value) {
  AT_DISPATCH_ALL_TYPES_AND(
      at::ScalarType::Bool, self.scalar_type(), "ScatterFill", [&]() {
        impl::ScatterFill<scalar_t>(self, dim, index, value);
      });
  return self;
}

Tensor& scatter_add_(
    Tensor& self,
    int64_t dim,
    const Tensor& index,
    const Tensor& src) {
  AT_DISPATCH_ALL_TYPES_AND(
      at::ScalarType::Bool, self.scalar_type(), "ScatterAdd", [&]() {
        impl::ScatterAdd<scalar_t>(self, dim, index, src);
      });
  return self;
}

Tensor& gather_out(
    Tensor& out,
    const Tensor& self,
    int64_t dim,
    const Tensor& index,
    bool sparse_grad) {
  AT_DISPATCH_ALL_TYPES_AND(
      at::ScalarType::Bool, self.scalar_type(), "Gather", [&]() {
        impl::Gather<scalar_t>(out, self, dim, index);
      });
  return out;
}

Tensor gather(
    const Tensor& self,
    int64_t dim,
    const Tensor& index,
    bool sparse_grad) {
  Tensor out = at::empty({0}, self.options());
  out.resize_(index.sizes());
  return at::AtenIpexTypeDPCPP::gather_out(out, self, dim, index, sparse_grad);
}

} // namespace AtenIpexTypeDPCPP
} // namespace at
