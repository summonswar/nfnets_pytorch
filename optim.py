import torch
from torch._C import is_grad_enabled
from torch.autograd import grad
from torch.optim import Optimizer

# Compute norm depending on the shape of x
def unitwise_norm(x):
    if (len(torch.squeeze(x).shape)) <= 1: # Scalars, vectors
        axis = 0
        keepdims = False
    elif len(x.shape) in [2,3]: # Linear layers
        # Original code: IO
        # Pytorch: OI
        axis = 1
        keepdims = True
    elif len(x.shape) == 4: # Conv kernels
        # Original code: HWIO
        # Pytorch: OIHW
        axis = [1, 2, 3]
        keepdims = True
    else:
        raise ValueError(f'Got a parameter with len(shape) not in [1, 2, 3, 4]! {x}')

    return torch.sqrt(torch.sum(torch.square(x), axis=axis, keepdim=keepdims))


# This is a copy of the pytorch SGD implementation
# enhanced with gradient clipping
class SGD_AGC(Optimizer):
    def __init__(self, params, lr:float, momentum=0, dampening=0,
                 weight_decay=0, nesterov=False, clipping:float=None, eps:float=1e-3):
        if lr < 0.0:
            raise ValueError("Invalid learning rate: {}".format(lr))
        if momentum < 0.0:
            raise ValueError("Invalid momentum value: {}".format(momentum))
        if weight_decay < 0.0:
            raise ValueError("Invalid weight_decay value: {}".format(weight_decay))

        defaults = dict(lr=lr, momentum=momentum, dampening=dampening,
                        weight_decay=weight_decay, nesterov=nesterov,
                        # Extra defaults
                        clipping=clipping,
                        eps=eps
                        )

        if nesterov and (momentum <= 0 or dampening != 0):
            raise ValueError("Nesterov momentum requires a momentum and zero dampening")
        super(SGD_AGC, self).__init__(params, defaults)

    def __setstate__(self, state):
        super(SGD_AGC, self).__setstate__(state)
        for group in self.param_groups:
            group.setdefault('nesterov', False)

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            weight_decay = group['weight_decay']
            momentum = group['momentum']
            dampening = group['dampening']
            nesterov = group['nesterov']

            # Extra values for clipping
            clipping = group['clipping']
            eps = group['eps']

            for p in group['params']:
                if p.grad is None:
                    continue
                d_p = p.grad

                # =========================
                # Gradient clipping
                if clipping is not None:
                    param_norm = torch.maximum(unitwise_norm(p), torch.tensor(eps).to(p.device))
                    grad_norm = unitwise_norm(d_p)
                    max_norm = param_norm * group['clipping']

                    trigger_mask = grad_norm > max_norm
                    clipped_grad = p.grad * (max_norm / torch.maximum(grad_norm, torch.tensor(1e-6).to(p.device)))
                    d_p = torch.where(trigger_mask, clipped_grad, d_p)
                # =========================

                if weight_decay != 0:
                    d_p = d_p.add(p, alpha=weight_decay)
                if momentum != 0:
                    param_state = self.state[p]
                    if 'momentum_buffer' not in param_state:
                        buf = param_state['momentum_buffer'] = torch.clone(d_p).detach()
                    else:
                        buf = param_state['momentum_buffer']
                        buf.mul_(momentum).add_(d_p, alpha=1 - dampening)
                    if nesterov:
                        d_p = d_p.add(buf, alpha=momentum)
                    else:
                        d_p = buf

                p.add_(d_p, alpha=-group['lr'])

        return loss

"""
class SGD_AGC(SGD):
    def __init__(self, params, lr, momentum=0, dampening=0,
                 weight_decay=0, nesterov=False, clipping:float=None, eps:float=1e-3):

        super(SGD_AGC, self).__init__(params=params, lr=lr, momentum=momentum, 
            dampening=dampening, weight_decay=weight_decay, nesterov=nesterov)

        self.defaults['clipping'] = clipping
        self.defaults['eps'] = eps
        self.defaults['clipping_low'] = 1e-6

        print(self.defaults)
 
    # Compute norm depending on the shape of x
    def _unitwise_norm(self, x):
        if (len(torch.squeeze(x).shape)) <= 1: # Scalars, vectors
            axis = None,
            keepdims = False
        elif len(x.shape) in [2,3]: # Linear layers
            # Original code: IO
            # Pytorch: OI
            axis = 1
            keepdims = True
        elif len(x.shape) == 4: # Conv kernels
            # Original code: HWIO
            # Pytorch: OIHW
            axis = [1, 2, 3]
            keepdims = True
        else:
            raise ValueError(f'Got a parameter with len(shape) not in [1, 2, 3, 4]! {x}')

        return torch.sqrt(torch.sum(torch.square(x), axis=axis, keepdim=keepdims))

    # Loop equivalent to pytorch sgd step implementation
    # Iterate over all gradients and clip them
    #
    # Theoretically it would be better to include this code directly in SGD optimizer
    # because now this step() function iterates two times over all params
    @torch.no_grad()
    def step(self, closure=None):
        for group in self.param_groups:
            clipping = group['clipping']
            eps = group['eps']
            clipping_low = group['clipping_low']

            for p in group['params']:
                if p.grad is None:
                    continue
                
                if clipping is not None:
                    param_norm = torch.maximum(self._unitwise_norm(p), torch.tensor(eps))
                    grad_norm = self._unitwise_norm(p.grad)
                    max_norm = param_norm * group['clipping']

                    trigger_mask = grad_norm > max_norm
                    clipped_grad = p.grad * (max_norm / torch.maximum(grad_norm, torch.tensor(clipping_low)))
                    grad = torch.where(trigger_mask, clipped_grad, grad)

        return super(SGD_AGC, self).step(closure=closure)
"""