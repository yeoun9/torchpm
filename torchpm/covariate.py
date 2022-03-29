from copy import deepcopy
from dataclasses import dataclass
import functools
from random import random
from typing import Any, Callable, ClassVar, List, Optional
from torch import nn
import random

import torch as tc
from torchpm.data import CSVDataset
from torchpm.models import FOCEInter
from torchpm.parameter import *
from torchpm.predfunction import PredictionFunctionModule
from . import *

@dataclass
class Covariate:
    dependent_parameter_names : List[str]
    dependent_parameter_initial_values : List[List[float]]
    independent_parameter_names : List[str]
    covariate_relationship_function : Callable[..., Dict[str,tc.Tensor]]
    
    def __post_init__(self) :
        pass

#사용자가 만든 Predfunction module을 받아서 covariate_model 클래스를 생성한다.
class CovariateModelDecorator :
    def __init__(self, covariates : List[Covariate]):
        self.covariates = covariates            
    
    def __call__(self, cls):
        if not issubclass(cls, predfunction.PredictionFunctionModule) :
            raise Exception('Decorated class must be ' + str(predfunction.PredictionFunctionModule))
        meta_self = self
        class CovariateModel(cls):
            
            def _set_estimated_parameters(self):
                super()._set_estimated_parameters()
                self.covariate_relationship_function = []    
                for i, cov in enumerate(meta_self.covariates):
                    function_name = ''
                    for ip_name, init_value in zip(cov.dependent_parameter_names, cov.dependent_parameter_initial_values) :
                        setattr(self, ip_name + '_theta', Theta(*init_value))
                        setattr(self, ip_name + '_eta', Eta())
                    setattr(self, '_covariate_relationship_function_' + str(i), cov.covariate_relationship_function)
                    # self.covariate_relationship_function.append(cov.covariate_relationship_function)

            def _calculate_parameters(self, parameters):
                super()._calculate_parameters(parameters)
                for i, cov in enumerate(meta_self.covariates):

                    para_dict = {}

                    # ip_dict : Dict[str, tc.Tensor] = {}
                    for name in cov.independent_parameter_names :
                        para_dict[name] = parameters[name]
                    
                    # dp_dict : Dict[str, tc.Tensor] = {}
                    for name in  cov.dependent_parameter_names :
                        pop_para_name = name + '_theta'
                        para_dict[pop_para_name] = getattr(self, pop_para_name)
                        ind_para_name = name + '_eta'
                        para_dict[ind_para_name] = getattr(self, ind_para_name)
                    
                    function = getattr(self, '_covariate_relationship_function_' + str(i))
                    
                    result_dict = function(para_dict)
                    for name, value in result_dict.items() :
                        parameters[name] = value

        return CovariateModel

@dataclass
class DeepCovariateSearching:
    dataset : CSVDataset
    base_model : predfunction.PredictionFunctionModule
    dependent_parameter_names : List[str]
    dependent_parameter_initial_values : List[List[float]]
    independent_parameter_names : List[str]

    def __post_init(self) :
        pass
    
    def _get_covariate_relationship_function(self, dependent_parameter_names, independent_parameter_names):
        idp_para_names_length = len(independent_parameter_names)
        dp_para_names_length = len(dependent_parameter_names)
        class CovariateRelationshipFunction(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.lin = nn.Sequential(
                            nn.Linear(idp_para_names_length, dp_para_names_length),
                            nn.Linear(dp_para_names_length, dp_para_names_length))

            def forward(self, para_dict : Dict[str, Any]) -> Dict[str, tc.Tensor] :
                idp_para_tensor = tc.stack([para_dict[name] for name in independent_parameter_names]).t()

                lin_r = self.lin(idp_para_tensor).t()
                para_result = {}
                for i, name in enumerate(dependent_parameter_names):
                    para_result[name] = para_dict[name + '_theta']() * tc.exp(para_dict[name + '_eta']() + lin_r[i])

                return para_result
        return CovariateRelationshipFunction
    
    def _get_model(self, dependent_parameter_names, dependent_parameter_initial_values, independent_parameter_names) :
        cov = Covariate(dependent_parameter_names,
                        dependent_parameter_initial_values,
                        independent_parameter_names,
                        self._get_covariate_relationship_function(dependent_parameter_names,
                                                                independent_parameter_names)())
        cov_model_decorator = CovariateModelDecorator([cov])
        CovModel = cov_model_decorator(self.base_model)

        theta_names = [name + '_theta' for name in self.dependent_parameter_names]
        eta_names = [name + '_eta' for name in self.dependent_parameter_names]
        

        dp_para_length = len(self.dependent_parameter_names)
        matrix = tc.rand(dp_para_length,dp_para_length)
        matrix = tc.mm(matrix, matrix.t())
        matrix.add_(tc.eye(dp_para_length))

        omega_init = matrix_to_lower_triangular_vector(matrix).tolist()
        omega = Omega(omega_init, False, requires_grads=True)
        
        #TODO 나중에 개선
        sigma = Sigma([[0.0177], [0.0762]], [True, True], requires_grads=[True, True])

        model = models.FOCEInter(dataset=self.dataset,
                                output_column_names=[], #TODO 나중에 추가
                                pred_function_module=CovModel, 
                                theta_names=theta_names,
                                eta_names= eta_names, 
                                eps_names= ['eps_0','eps_1'], #TODO 나중에 개선
                                omega=omega, 
                                sigma=sigma)
        return model.to(self.dataset.device)

    def run(self, learning_rate : float = 1,
                    checkpoint_file_path: Optional[str] = None,
                    tolerance_grad : float= 1e-3,
                    tolerance_change : float = 1e-3,
                    max_iteration : int = 1000) :

        self.independent_parameter_names_candidate = deepcopy(self.independent_parameter_names)

        pre_total_loss = self._fit(learning_rate = learning_rate, 
                                tolerance_grad = tolerance_grad, 
                                tolerance_change= tolerance_change, 
                                max_iteration=max_iteration) 
        for name in self.independent_parameter_names :
            self.independent_parameter_names_candidate.remove(name)

            total_loss = self._fit(learning_rate = learning_rate, 
                                tolerance_grad = tolerance_grad, 
                                tolerance_change= tolerance_change, 
                                max_iteration=max_iteration)
            print('=================================================',
                '\n covariate : ', name,
                '\n total : ', total_loss,
                '\n pre total : ', pre_total_loss,
                '\n total-pretotal: ', total_loss - pre_total_loss,
                '\n=================================================')
            #TODO p-value 찾아서 쓰기
            if total_loss - pre_total_loss  < 3.84 :
                print('==========================================',
                '\n Removed :', name,
                '\n===================================')
                pre_total_loss = total_loss
            else :
                self.independent_parameter_names_candidate.append(name)
        
        return self.independent_parameter_names_candidate

    def _fit(self, learning_rate : float = 1,
                    checkpoint_file_path: Optional[str] = None,
                    tolerance_grad : float= 1e-2,
                    tolerance_change : float = 1e-2,
                    max_iteration : int = 1000) :
        model = self._get_model(self.dependent_parameter_names,
                                self.dependent_parameter_initial_values,
                                self.independent_parameter_names_candidate)
        
        model.fit_population(learning_rate = learning_rate, 
                            tolerance_grad = tolerance_grad, 
                            tolerance_change= tolerance_change, 
                            max_iteration=max_iteration)

        result = model.descale().evaluate()

        total_loss = tc.tensor(0., device=self.dataset.device)
        for id, values in result.items() :
            total_loss += values['loss']
        
        return total_loss