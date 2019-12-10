#pragma once

#include <ATen/Tensor.h>
#include <c10/core/Storage.h>
#include <c10/core/TensorImpl.h>

namespace torch_ipex {

// Tensor implementation class used to be fed to the at::Tensor.
// Its scope is just to handle an XLATensor.
class IPEXTensorImpl : public c10::TensorImpl {
 public:
  explicit IPEXTensorImpl(const at::Tensor& tensor);
};

} // namespace torch_ipex
