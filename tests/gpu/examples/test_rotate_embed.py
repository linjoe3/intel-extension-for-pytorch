import torch
from torch.testing._internal.common_utils import TestCase

import intel_extension_for_pytorch  # noqa

cpu_device = torch.device("cpu")
dpcpp_device = torch.device("xpu")

def rotate_every_two(x):
    x1 = x[:, :, :, ::2]
    x2 = x[:, :, :, 1::2]
    x = torch.stack((-x2, x1), dim=-1)
    return x.flatten(-2)  # in einsum notation: rearrange(x, '... d j -> ... (d j)')

def apply_rotary_pos_emb(tensor: torch.Tensor, sin: torch.Tensor, cos: torch.Tensor) -> torch.Tensor:
    return rotate_every_two(tensor) * sin + tensor * cos

def rotate_half(x):
    """Rotates half the hidden dims of the input."""
    x1 = x[..., : x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)

def apply_rotary_pos_emb_half(q, k, sin, cos):
    q_embed = (q * cos) + (rotate_half(q) * sin)
    k_embed = (k * cos) + (rotate_half(k) * sin)
    return q_embed, k_embed

class TestNNMethod(TestCase):
    def test_rotary_embed(self):
        test_tensor_size = [(64, 32, 1, 16),
                            (64, 32, 1, 32),
                            (64, 32, 1, 130),
                            (64, 32, 1, 1028),
                            (64, 32, 1, 2048)]
        for size in test_tensor_size:
            tensor = torch.randn(size).float().to("xpu")
            sin = torch.randn(size).float().to("xpu")
            cos = torch.randn(size).float().to("xpu")

            ref = apply_rotary_pos_emb(tensor, sin, cos)
            out = torch.empty_like(tensor)
            kernel_out = torch.ops.torch_ipex.apply_rotary_embedding(tensor, sin, cos, tensor)
            self.assertEqual(tensor, ref)

    def test_rotary_embed_half(self):
        test_tensor_size = [(64, 32, 1, 16),
                            (64, 32, 1, 32),
                            (64, 32, 1, 130),
                            (64, 32, 1, 1028),
                            (64, 32, 1, 2048)]
        for size in test_tensor_size:
            query = torch.randn(size).float().to("xpu")
            key = torch.randn(size).float().to("xpu")
            sin = torch.randn(size).float().to("xpu")
            cos = torch.randn(size).float().to("xpu")

            q_ref, k_ref = apply_rotary_pos_emb_half(query, key, sin, cos)
            
            q_out = torch.empty_like(query)
            k_out = torch.empty_like(key)
            torch.ops.torch_ipex.apply_rotary_embedding_half(query, key, sin, cos, q_out, k_out)
            self.assertEqual(q_out, q_ref)
            self.assertEqual(k_out, k_ref)