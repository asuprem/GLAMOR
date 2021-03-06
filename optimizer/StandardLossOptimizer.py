import torch
from loss.builders import LossBuilder

class StandardLossOptimizer:
    """ Optimizer for Loss Functions

    This sets up optimizer for the loss functions in a LossBuilder. Not applicable everywhere. Not used everywhere because most losses will have zero differentiable parametersif 
    
    However, it will be useful for losses like the ProxyNCA, which need to learn proxies during training.

    """
    def __init__(self, base_lr, lr_bias, gpus, weight_decay=None, weight_bias=None):
        """ Initializes the optimizer builder.

        Args:
        base_lr (float): Base learning rate for optimizer
        lr_bias (float): Multiplicative factor for bias parameters
        gpus (int): Number of GPUs for lr scaling
        weight_decay (float): Weight decay for decoupled weight decay optimizers like AdamW
        weight_bias (float): Multiplicative factor for bias parameters in weight decay optimizers

        Methods:
        build:  builds an optimizer given optimizer name and torch model

        """
        self.base_lr = base_lr
        self.gpus = gpus
        self.weight_decay = weight_decay
        self.lr_bias = lr_bias
        self.weight_bias = weight_bias

    def build(self, loss_builder: LossBuilder, name = 'Adam', **kwargs):
        """ Builds an optimizer.

        Args:
        loss_builder (loss.builders.LossBuilder): A LossBuilder object
        name (str): name of torch.optim object to build
        kwargs (dict): any parameters that need to be passed into the optimizer

        Returns:
        torch.optim object

        """
        params = []
        for key, value in loss_builder.named_parameters():
            if value.requires_grad:
                # if "bias" in key:
                #    learning_rate = self.base_lr * self.lr_bias
                #    weight_decay = self.weight_decay * self.weight_bias
                # else:
                learning_rate = self.base_lr * self.gpus
                weight_decay = self.weight_decay
                params += [{"params": [value], "lr":learning_rate, "weight_decay": weight_decay}]
        if len(params) == 0:
            return None
        optimizer = __import__('torch.optim', fromlist=['optim'])
        optimizer = getattr(optimizer, name)
        optimizer = optimizer(params, **kwargs)
        return optimizer


