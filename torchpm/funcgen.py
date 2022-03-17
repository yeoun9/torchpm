import abc
from typing import ClassVar, List, Optional, Dict, Iterable, Tuple, Union

import torch as tc

class ParameterGenerator(tc.nn.Module) :
    def __init__(self) -> None:
        super().__init__()

    def forward(self, theta, eta, cmt, amt, *cov) -> Dict[str, tc.Tensor] :
        """
        pk parameter calculation
        returns: 
            typical values of pk parameter
        """
        pass

class PredFunctionGenerator(tc.nn.Module) :
    def __init__(self) -> None:
            super().__init__()

    def forward(self, t, y, theta, eta, cmt, amt, rate, parameters) :
        """
        predicted value calculation
        returns: 
            vector of predicted values with respect to t
        """
        pass

class ErrorFunctionGenerator(metaclass=abc.ABCMeta) :
    @abc.abstractmethod
    def __call__(self, y_pred, eps, theta, cmt, parameters, *cov) -> Tuple(tc.Tensor, Dict[str, tc.Tensor]):
        """
        error value calculation
        returns: 
            vector of dependent value with respect to y_pred
        """
        pass
