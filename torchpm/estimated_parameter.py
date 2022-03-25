from numbers import Number


from typing import List, Optional, Dict, Iterable, Union


import torch as tc


from torch import nn


from .misc import *



class Theta(nn.Module):


    """


    Args:


        init_value: initial value of scala


        lower_boundary: lower boundary of scala


        upper_boundary: upper boundary of scala


    Attributes: .


    """


    def __init__(self, *init_value: float, requires_grad = True):
        super().__init__()

        if len(init_value) > 3 :
            raise Exception('it must be len(init_value) < 3')


        self.is_scale = True


        self.lb : tc.Tensor = tc.tensor(0.)
        iv = tc.tensor(0)
        self.ub : tc.Tensor = tc.tensor(1.0e6)
        

        if len(init_value) == 1 :


            iv = tc.tensor(init_value[1])


            if self.lb > init_value :


                self.lb = tc.tensor(init_value)


            if self.ub < init_value :


                self.ub = tc.tensor(init_value)
        elif len(init_value) == 2 :
            if init_value[1] < init_value[0]:

                raise Exception('lower value must be lower than upper value.')
            
            self.lb = tc.tensor(init_value[0])
            iv = tc.tensor((init_value[0] + init_value[1])/2)
            self.ub = tc.tensor(init_value[1])


        elif len(init_value) == 3 :


            if init_value[1] < init_value[0]:


                raise Exception('lower value must be lower than initial value.') 


            if init_value[1] > init_value[2] :


                raise Exception('upper value must be upper than initial value.')


            self.lb = tc.tensor(init_value[0])


            iv = tc.tensor(init_value[1])


            self.ub = tc.tensor(init_value[2])
                


        lb = self.lb


        ub = self.ub



        self.alpha = 0.1 - tc.log((iv - lb)/(ub - lb)/(1 - (iv - lb)/(ub - lb)))


        self.parameter_value = nn.Parameter(tc.tensor(0.1), requires_grad = requires_grad)



    def descale(self) :


        if self.is_scale:


            with tc.no_grad() :


                self.scaled_parameter_for_save = self.parameter_value.data.clone()


                self.parameter_value.data = self.forward()


                self.is_scale = False
    


    def scale(self) :


        if not self.is_scale and self.scaled_parameter_for_save is not None :


            with tc.no_grad() :


                self.parameter_value.data = self.scaled_parameter_for_save


                self.scaled_parameter_for_save = None


                self.is_scale = True


    def forward(self) :


        if self.is_scale :


            return tc.exp(self.parameter_value - self.alpha)/(tc.exp(self.parameter_value - self.alpha) + 1)*(self.ub - self.lb) + self.lb


        else :
            return self.parameter_value



class Eta(nn.Module) :


    def __init__(self) -> None:
        super().__init__()


        self.parameter_values = nn.ParameterDict()
    


    def forward(self):


        return self.parameter_values[str(self.id)]



class Eps(nn.Module):


    def __init__(self) -> None:
        super().__init__()


        self.parameter_values : Dict[str, nn.Parameter] = {}
    


    def forward(self):


        return self.parameter_values[str(self.id)]




class CovarianceMatrix(nn.Module) :


    def __init__(self,
                lower_triangular_vectors_init : Union[List[List[float]], List[float]] , 
                diagonals : List[bool],
                requires_grads : Union[List[bool], bool] = True) :
        super().__init__()

        


        lower_triangular_vectors_init_tensor = tc.tensor(lower_triangular_vectors_init)
        if lower_triangular_vectors_init_tensor.dim() == 1 :
            lower_triangular_vectors_init_tensor = lower_triangular_vectors_init_tensor.unsqueeze(0)


        # r = []


        # for vector in lower_triangular_vectors_init:


        #     r.append(tc.tensor(vector))


        # lower_triangular_vectors_init = r



        if len(lower_triangular_vectors_init_tensor) != len(diagonals) :


            raise RuntimeError('The lengths of lower_triangular_vectors_init and diagonals must match.')


        if isinstance(requires_grads, Iterable) and len(lower_triangular_vectors_init_tensor) != len(requires_grads) :


            raise RuntimeError('The lengths of lower_triangular_vectors_init and requires_grads must match.')


        self.scaled_parameter_for_save : Optional[List[nn.Parameter]] = None

        self.is_scale = True


        self.diagonals = diagonals


        self.lower_triangular_vector_lengthes = []


        for init_vector in lower_triangular_vectors_init_tensor :


            l = init_vector.size()[0]


            self.lower_triangular_vector_lengthes.append(l)



        self.parameter_values = nn.ParameterList()
        


        if type(requires_grads) is bool :


            for length in self.lower_triangular_vector_lengthes:    


                self.parameter_values.append(nn.Parameter(tc.tensor([0.1]*length, requires_grad=requires_grads, device=lower_triangular_vectors_init_tensor[0].device)))


        elif isinstance(requires_grads, Iterable)  :


            for length, requires_grad in zip(self.lower_triangular_vector_lengthes, requires_grads) :


                self.parameter_values.append(nn.Parameter(tc.tensor([0.1]*length, requires_grad=requires_grad, device=lower_triangular_vectors_init_tensor[0].device)))
        


        self.scales = []


        for init_vector, diagonal in zip(lower_triangular_vectors_init_tensor, self.diagonals):


            s = self._set_scale(init_vector, diagonal)
            self.scales.append(s)



    def _set_scale(self, lower_triangular_vector_init, diagonal) :


        var_mat = lower_triangular_vector_to_covariance_matrix(lower_triangular_vector_init, diagonal)


        m1 = tc.linalg.cholesky(var_mat).transpose(-2, -1).conj()


        v1 = m1.diag()


        m2 = tc.abs(10 * (m1 - v1.diag()) + (v1/tc.exp(tc.tensor(0.1))).diag())


        return m2.t()
    


    def calculate_scaled_matrix(self, scaled_matrix, scale) :


        maT = scaled_matrix * scale


        diag_part = scaled_matrix.diag().exp() * scale.diag()


        maT = tc.tril(maT) - maT.diag().diag() + diag_part.diag()


        return maT @ maT.t()



    def descale(self) :


        if self.is_scale is True:


            with tc.no_grad() :


                self.scaled_parameters_for_save = []


                for parameter in self.parameter_values:
                    self.scaled_parameters_for_save.append(parameter.data.clone())
                


                matrixes = []


                for vector, scale, diagonal in zip(self.parameter_values, self.scales, self.diagonals) :


                    mat = lower_triangular_vector_to_covariance_matrix(vector, diagonal)


                    matrixes.append(self.calculate_scaled_matrix(mat, scale.to(mat.device)))
                


                for matrix, para, diagonal in zip(matrixes, self.parameter_values, self.diagonals) :


                    if diagonal :


                        para.data = tc.diag(matrix, 0)


                    else :


                        para.data = matrix_to_lower_triangular_vector(matrix)


            self.is_scale = False
    


    def scale(self) :


        if self.scale is False and self.scaled_parameter_for_save is not None:


            with tc.no_grad() :


                for parameter, data in zip(self.parameter_values, self.scaled_parameter_for_save):


                    parameter.data = data  


            self.scaled_parameter_for_save : Optional[List[nn.Parameter]] = None


            self.is_scale = True



    def forward(self):


        flat_tensors = self.parameter_values


        diagonals = self.diagonals


        scales = self.scales


        m = []


        if self.is_scale :


            for tensor, scale, diagonal in zip(flat_tensors, scales, diagonals) :


                mat = lower_triangular_vector_to_covariance_matrix(tensor, diagonal)


                m.append(self.calculate_scaled_matrix(mat, scale.to(mat.device)))


        else :


            for tensor, diagonal in zip(flat_tensors, diagonals) :


                m.append(lower_triangular_vector_to_covariance_matrix(tensor, diagonal))


        return tc.block_diag(*m)



class Omega(CovarianceMatrix):
    
    def __init__(self, lower_triangular_vectors_init: Union[List[List[float]], List[float]], diagonals: List[bool], requires_grads: Union[List[bool], bool] = True):
        super().__init__(lower_triangular_vectors_init, diagonals, requires_grads)



class Sigma(CovarianceMatrix) :
    
    def __init__(self, lower_triangular_vectors_init: Union[List[List[float]], List[float]], diagonals: List[bool], requires_grads: Union[List[bool], bool] = True):
        super().__init__(lower_triangular_vectors_init, diagonals, requires_grads)