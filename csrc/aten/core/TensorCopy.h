#pragma once

#include <c10/core/TensorImpl.h>

using namespace at;

namespace at {
namespace native {

void TensorImpl_copy(TensorImpl* dst, TensorImpl* src);
template <typename ScalarType>
TensorImpl* TensorImpl_newClone(TensorImpl* self);
template <typename ScalarType>
TensorImpl* TensorImpl_newContiguous(TensorImpl* self);
template <typename ScalarType>
void TensorImpl_freeCopyTo(TensorImpl* self, TensorImpl* dst);
template <typename ScalarType>
void TensorImpl_copyIgnoringOverlaps(TensorImpl* dst, TensorImpl* src);
} // namespace native
} // namespace at