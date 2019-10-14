from .ReIDLossBuilder import ReIDLossBuilder
from .CarZamLossBuilder import CarZamLossBuilder


class LossBuilder:
    def __init__(self):
        pass

    def __call__(self,**kwargs):
        """Call operator of the loss builder.

        This returns the sum of each individual loss provided in the initialization, multiplied by their respective loss_lambdas. 
        TODO update this + CarZam base model forward to deal with logits as well if necessary

        Args (kwargs only):
            labels: Torch tensor of shape (batch_size, 1). The class labels.
            features: Torch tensor of shape (batch_size, embedding_dimensions). The feature embeddings generated by the ReID model.
        """
        loss = 0.0
        for idx, fn in enumerate(self.loss):
            #loss += self.loss_lambda[idx] * fn(kwargs.get(self.LOSS_PARAMS[self.loss_fn[idx]]['args'][0]), kwargs.get(self.LOSS_PARAMS[self.loss_fn[idx]]['args'][1]), kwargs.get(self.LOSS_PARAMS[self.loss_fn[idx]]['args'][2]))
            loss += self.loss_lambda[idx] * fn(*[ kwargs.get(arg_name)   for arg_name in self.LOSS_PARAMS[self.loss_fn[idx]]['args']])
        return loss