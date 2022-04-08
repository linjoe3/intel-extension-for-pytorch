import torch
import torch.nn as nn
from torch.testing._internal.common_utils import (TestCase,
                                                  repeat_test_for_types)

import intel_extension_for_pytorch

import pytest

cpu_device = torch.device("cpu")
dpcpp_device = torch.device("xpu")


class TestNNMethod(TestCase):
    def test_adaptive_avg_pool2d(self, dtype=torch.float):
        x_cpu = torch.ones([1, 1, 8, 8], device=cpu_device)
        grad_cpu = torch.ones([1, 1, 2, 2], device=cpu_device)
        x_dpcpp = x_cpu.to(dpcpp_device)
        grad_dpcpp = grad_cpu.to(dpcpp_device)
        self.assertEqual(x_cpu, x_dpcpp.to(cpu_device))
        self.assertEqual(grad_cpu, grad_dpcpp.to(cpu_device))

        avg_pool = nn.AdaptiveAvgPool2d((2, 2))
        # conv1 = nn.Conv2d(1, 1, kernel_size=3, stride=1, padding=1, bias=True)

        x_cpu.requires_grad_(True)

        # y_cpu = conv1(x_cpu)
        y_cpu = avg_pool(x_cpu)
        print("y_cpu", y_cpu)
        # conv1.zero_grad()
        output_cpu = y_cpu.backward(grad_cpu)
        print("x_cpu.grad", x_cpu.grad)

        x_dpcpp.requires_grad_(True)
        avg_pool.to(dpcpp_device)
        # conv1 = conv1.dpcpp()
        # y_dpcpp = conv1(x_dpcpp)
        y_dpcpp = avg_pool(x_dpcpp)
        print("y_dpcpp", y_dpcpp.cpu())
        # conv1.zero_grad()
        output_dpcpp = y_dpcpp.backward(grad_dpcpp)
        print("x_dpcpp.grad", x_dpcpp.grad.cpu())
        self.assertEqual(x_cpu.grad, x_dpcpp.grad.to(cpu_device))

    def test_channels_last_simple_fwd(self, dtype=torch.float):
        x_cpu = torch.ones([1, 1, 8, 8], device=cpu_device)
        x_dpcpp = x_cpu.to(dpcpp_device).to(memory_format=torch.channels_last)

        avg_pool = nn.AdaptiveAvgPool2d((2, 2))

        y_cpu = avg_pool(x_cpu)
        print("y_cpu", y_cpu)

        avg_pool.to(dpcpp_device)
        y_dpcpp = avg_pool(x_dpcpp)
        print("y_dpcpp", y_dpcpp.cpu())
        self.assertEqual(y_cpu, y_dpcpp.to(cpu_device))

    def test_channels_last_simple_bwd(self, dtype=torch.float):
        x_cpu = torch.ones([1, 1, 8, 8], device=cpu_device)
        grad_cpu = torch.ones([1, 1, 2, 2], device=cpu_device)
        x_dpcpp = x_cpu.to(dpcpp_device).to(memory_format=torch.channels_last)
        grad_dpcpp = grad_cpu.to(dpcpp_device)
        avg_pool = nn.AdaptiveAvgPool2d((2, 2))

        x_cpu.requires_grad_(True)

        y_cpu = avg_pool(x_cpu)
        print("y_cpu", y_cpu)
        output_cpu = y_cpu.backward(grad_cpu)
        print("x_cpu.grad", x_cpu.grad)

        x_dpcpp.requires_grad_(True)
        avg_pool.to(dpcpp_device)
        y_dpcpp = avg_pool(x_dpcpp)
        print("y_dpcpp", y_dpcpp.cpu())
        output_dpcpp = y_dpcpp.backward(grad_dpcpp)
        print("x_dpcpp.grad", x_dpcpp.grad.cpu())
        self.assertEqual(x_cpu.grad, x_dpcpp.grad.to(cpu_device))

    @repeat_test_for_types([torch.float, torch.bfloat16])
    def test_adaptive_avg_pool_3D(self, dtype=torch.float):
        x = torch.randn([30, 40, 50])
        grad = torch.randn([30, 2, 2])
        mem_format = torch.channels_last
        m = nn.AdaptiveAvgPool2d((2, 2))

        # 3D contiguous input
        # CPU
        input_cpu = x.clone()
        input_cpu.requires_grad_(True)
        grad_cpu = grad.clone()
        output_cpu = m(input_cpu)
        output_cpu.backward(grad_cpu)

        # XPU
        input_xpu = x.clone().to(dpcpp_device)
        input_xpu.requires_grad_(True)
        grad_xpu = grad.clone().to(dpcpp_device)
        output_xpu = m(input_xpu)
        output_xpu.backward(grad_xpu)

        self.assertEqual(output_cpu, output_xpu.to(cpu_device))
        self.assertEqual(input_cpu.grad, input_xpu.grad.to(cpu_device))

        # 3D non-contiguous input
        # CPU
        grad = torch.randn([40, 2, 2])
        input_cpu = x.clone().transpose(0, 1)
        input_cpu.requires_grad_(True)
        grad_cpu = grad.clone()
        output_cpu = m(input_cpu)
        output_cpu.backward(grad_cpu)

        # XPU
        input_xpu = x.clone().transpose(0, 1).to(dpcpp_device)
        input_xpu.requires_grad_(True)
        grad_xpu = grad.clone().to(dpcpp_device)
        output_xpu = m(input_xpu)
        output_xpu.backward(grad_xpu)

        self.assertEqual(output_cpu, output_xpu.to(cpu_device))
        self.assertEqual(input_cpu.grad, input_xpu.grad.to(cpu_device))

    @repeat_test_for_types([torch.float, torch.bfloat16])
    def test_adaptive_avg_pool_4D(self, dtype=torch.float):
        x = torch.randn([20, 30, 40, 50])
        grad = torch.randn([20, 30, 2, 2])
        m = nn.AdaptiveAvgPool2d((2, 2))

        # 4D contiguous input
        # CPU
        input_cpu = x.clone()
        input_cpu.requires_grad_(True)
        grad_cpu = grad.clone()
        output_cpu = m(input_cpu)
        output_cpu.backward(grad_cpu)

        # XPU
        input_xpu = x.clone().to(dpcpp_device)
        input_xpu.requires_grad_(True)
        grad_xpu = grad.clone().to(dpcpp_device)
        output_xpu = m(input_xpu)
        output_xpu.backward(grad_xpu)

        self.assertEqual(output_cpu, output_xpu.to(cpu_device))
        self.assertEqual(input_cpu.grad, input_xpu.grad.to(cpu_device))

        # 4D channel_last input
        # CPU
        mem_format = torch.channels_last
        input_cpu = x.clone()
        input_cpu.requires_grad_(True)
        grad_cpu = grad.clone()
        output_cpu = m(input_cpu)
        output_cpu.backward(grad_cpu)

        # XPU
        input_xpu = x.clone().contiguous(memory_format=mem_format).to(dpcpp_device)
        input_xpu.requires_grad_(True)
        grad_xpu = grad.clone().contiguous(memory_format=mem_format).to(dpcpp_device)
        output_xpu = m(input_xpu)
        output_xpu.backward(grad_xpu)

        self.assertEqual(output_cpu, output_xpu.contiguous().to(cpu_device))
        self.assertEqual(input_cpu.grad, input_xpu.grad.contiguous().to(cpu_device))

        # 4D non-contiguous input
        # CPU
        input_cpu = x.clone().transpose(2, 3)
        input_cpu.requires_grad_(True)
        grad_cpu = grad.clone().transpose(2, 3)
        output_cpu = m(input_cpu)
        output_cpu.backward(grad_cpu)

        # XPU
        input_xpu = x.clone().transpose(2, 3).to(dpcpp_device)
        input_xpu.requires_grad_(True)
        grad_xpu = grad.clone().transpose(2, 3).to(dpcpp_device)
        output_xpu = m(input_xpu)
        output_xpu.backward(grad_xpu)

        self.assertEqual(output_cpu, output_xpu.to(cpu_device))
        self.assertEqual(input_cpu.grad, input_xpu.grad.to(cpu_device))
