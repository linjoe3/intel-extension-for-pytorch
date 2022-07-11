import torch
from typing import Union
from torch.types import Device
from torch._utils import _get_device_index as _torch_get_device_index


def _get_device_index(device: Union[Device, str, int], optional: bool = False,
                      allow_cpu: bool = False) -> int:
    r"""Gets the device index from :attr:`device`, which can be a torch.device
    object, a Python integer, or ``None``.

    If :attr:`device` is a torch.device object, returns the device index if it
    is a XPU device. Note that for a XPU device without a specified index,
    i.e., ``torch.device('xpu')``, this will return the current default XPU
    device if :attr:`optional` is ``True``. If :attr:`allow_cpu` is ``True``,
    CPU devices will be accepted and ``-1`` will be returned in this case.

    If :attr:`device` is a Python integer, it is returned as is.

    If :attr:`device` is ``None``, this will return the current default XPU
    device if :attr:`optional` is ``True``.
    """
    if isinstance(device, int):
        device = 'xpu:' + str(device)
    if device is None and optional:
        device = 'xpu:0'
    if isinstance(device, str):
        device = torch.device(device)
    if isinstance(device, torch.device):
        if allow_cpu:
            if device.type not in {'xpu', 'cpu'}:
                raise ValueError('Expected a xpu or cpu device, but got: {}'.format(device))
        elif device.type != 'xpu':
            raise ValueError('Expected a xpu device, but got: {}'.format(device))
    device_index = _torch_get_device_index(device, optional, allow_cpu)
    if device_index is None:
        return 0
    else:
        return device_index


# def _dummy_type(name: str) -> type:
#     def init_err(self):
#         class_name = self.__class__.__name__
#         raise RuntimeError(
#             "Tried to instantiate dummy base class {}".format(class_name))
#     return type(name, (object,), {"__init__": init_err})