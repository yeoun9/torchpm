import time
from typing import Callable, List, Dict, Optional
import torch as tc
import torch.distributed as dist

from .estimated_parameter import *
from .data import CSVDataset
from . import predfunction
from . import loss
from .misc import *

import itertools

class FOCEInter(tc.nn.Module) :

    def __init__(self,
                 pred_function_module : predfunction.PredictionFunctionModule,
                 theta_names : List[str],
                 eta_names : List[List[str]],
                 eps_names : List[List[str]],
                 omega : Omega,
                 sigma : Sigma,
                objective_function : loss.ObjectiveFunction = loss.FOCEInterObjectiveFunction()):
        super(FOCEInter, self).__init__()
        self.pred_function_module = pred_function_module


        self.theta_names = theta_names
        self.eta_names = eta_names
        self.eps_names = eps_names
        self.omega = omega
        self.sigma = sigma
        self.objective_function = objective_function
        
    def forward(self, dataset):
        
        pred_output = self.pred_function_module(dataset)

        etas = pred_output['etas']
        eta = []
        for eta_names in self.eta_names:
            for eta_name in eta_names:
                eta.append(etas[eta_name])

        epss = pred_output['epss']
        eps = []
        for eps_names in self.eps_names:
            for eps_name in eps_names:
                eps.append(epss[eps_name])

        y_pred, g, h = self._partial_different(pred_output['y_pred'], eta, eps)

        eta = tc.stack(eta)
        eps = tc.stack(eps)

        return y_pred, eta, eps, g, h, self.omega().to(dataset.device), self.sigma().to(dataset.device), pred_output['mdv_mask'], pred_output['output_columns']
    
    def _partial_different(self, y_pred, eta, eps):
        eta_size = len(eta)
        eps_size = len(eps)

        g = tc.zeros(y_pred.size()[0], eta_size, device = y_pred.device)
        for i_g, y_pred_elem in enumerate(y_pred) :
            if eta_size > 0 :
                for i_eta, cur_eta in enumerate(eta) :
                    g_elem = tc.autograd.grad(y_pred_elem, cur_eta, create_graph=True, allow_unused=True, retain_graph=True)
                    g[i_g, i_eta] = g_elem[0]
        
        h = tc.zeros(y_pred.size()[0], eps_size, device = y_pred.device)
        for i_h, y_pred_elem in enumerate(y_pred) :
            if eps_size > 0 :
                for i_eps, cur_eps in enumerate(eps):
                    h_elem = tc.autograd.grad(y_pred_elem, cur_eps, create_graph=True, allow_unused=True, retain_graph=True)
                    h[i_h,i_eps] = h_elem[0][i_h]
        return y_pred, g, h

    def optimization_function(self, dataset, optimizer, checkpoint_file_path : Optional[str] = None) -> Callable:
        """
        optimization function for L-BFGS 
        Args:
            dataset: model dataset
            optimizer: L-BFGS optimizer
            checkpoint_file_path : saving for optimized parameters
        """
        start_time = time.time()

        dataloader = tc.utils.data.DataLoader(dataset, batch_size=None, shuffle=False, num_workers=0)

        def fit() :
            optimizer.zero_grad()
            total_loss = tc.zeros([], device = dataset.device)
            
            for data, y_true in dataloader:
                y_pred, eta, eps, g, h, omega, sigma, mdv_mask, parameters = self(data)
 
                y_pred = y_pred.masked_select(mdv_mask)
                eta_size = g.size()[-1]
                if eta_size > 0 :
                    g = g.t().masked_select(mdv_mask).reshape((eta_size,-1)).t()
                eps_size = h.size()[-1]
                if eps_size > 0:
                    h = h.t().masked_select(mdv_mask).reshape((eps_size,-1)).t()
 
                y_true_masked = y_true.masked_select(mdv_mask)
                loss = self.objective_function(y_true_masked, y_pred, g, h, eta, omega, sigma)
                loss.backward()
                
                total_loss = total_loss + loss
            
            if checkpoint_file_path is not None :
                tc.save(self.state_dict(), checkpoint_file_path)
        
            print('running_time : ', time.time() - start_time, '\t total_loss:', total_loss)
            return total_loss
        return fit
    
    def optimization_function_for_multiprocessing(self, rank, dataset, optimizer, checkpoint_file_path : Optional[str] = None):
        """
        optimization function for L-BFGS multiprocessing
        Args:
            rank : multiprocessing thread number
            dataset: model dataset divided
            optimizer: L-BFGS optimizer
            checkpoint_file_path : saving for optimized parameters
        """
        start_time = time.time()

        dataloader = tc.utils.data.DataLoader(dataset, batch_size=None, shuffle=False, num_workers=0)
        def fit() :
            optimizer.zero_grad()
            total_loss = tc.zeros([], device = self.pred_function_module.dataset.device)
        
            for data, y_true in dataloader:
                y_pred, eta, eps, g, h, omega, sigma, mdv_mask, parameters = self(data)
 
                y_pred = y_pred.masked_select(mdv_mask)
                eta_size = g.size()[-1]
                g = g.t().masked_select(mdv_mask).reshape((eta_size,-1)).t()
                eps_size = h.size()[-1]
                h = h.t().masked_select(mdv_mask).reshape((eps_size,-1)).t()
 
                y_true_masked = y_true.masked_select(mdv_mask)
                loss = self.objective_function(y_true_masked, y_pred, g, h, eta, omega, sigma)
                loss.backward()
                
                total_loss.add_(loss)
            
            with tc.no_grad() :
                for param in self.parameters():
                    grad_cur = param.grad
                    if grad_cur is None :
                        grad_cur = tc.zeros_like(param)
                        dist.all_reduce(grad_cur, op=dist.ReduceOp.SUM)
                        param.grad = grad_cur
                    else: 
                        dist.all_reduce(param.grad, op=dist.ReduceOp.SUM)
                
                dist.all_reduce(total_loss, op=dist.ReduceOp.SUM)
                if rank == 0 :
                    print('running_time : ', time.time() - start_time, '\t total_loss:', total_loss)
                if rank == 0 and checkpoint_file_path is not None :
                    tc.save(self.state_dict(), checkpoint_file_path)
            return total_loss
        return fit

    def evaluate(self):

        dataloader = tc.utils.data.DataLoader(self.pred_function_module.dataset, batch_size=None, shuffle=False, num_workers=0)

        state = self.state_dict()
        
        total_loss = tc.tensor(0., device = self.pred_function_module.dataset.device)
        # self.pred_function_module.reset_epss()

        losses : Dict[str, float] = {}
        times : Dict[str, tc.Tensor] = {}
        preds : Dict[str, tc.Tensor] = {} 
        cwress : Dict[str, tc.Tensor] = {}
        mdv_masks : Dict[str, tc.Tensor] = {}
        ouput_columns : Dict[str, tc.Tensor] = {}
        for data, y_true in dataloader:

            y_pred, eta, eps, g, h, omega, sigma, mdv_mask, parameter = self(data)
            id = str(int(data[:,self.pred_function_module._column_names.index('ID')][0]))

            y_pred_masked = y_pred.masked_select(mdv_mask)
            eta_size = g.size()[-1]
            if eta_size >  0 :
                g = g.t().masked_select(mdv_mask).reshape((eta_size,-1)).t()
            
            eps_size = h.size()[-1]
            if eps_size > 0 :
                h = h.t().masked_select(mdv_mask).reshape((eps_size,-1)).t()

            y_true_masked = y_true.masked_select(mdv_mask)
            loss = self.objective_function(y_true_masked, y_pred_masked, g, h, eta, omega, sigma)
            
            cwress[id] = cwres(y_true_masked, y_pred_masked, g, h, eta, omega, sigma)
            preds[id] = y_pred
            losses[id] = float(loss)
            times[id] = data[:,self.pred_function_module._column_names.index('TIME')]
            mdv_masks[id] = mdv_mask
            
            ouput_columns[id] = parameter
                        
            with tc.no_grad() :
                total_loss.add_(loss)
            
        self.load_state_dict(state, strict=False)
        
        return {'total_loss': total_loss, 
                'losses': losses, 
                'times': times, 
                'preds': preds, 
                'cwress': cwress,
                'mdv_masks': mdv_masks,
                'parameters': ouput_columns}
    
    def descale(self) :
        self.pred_function_module.descale()
        self.omega.descale()
        self.sigma.descale()
        return self
    
    def parameters_for_individual(self) :
        parameters = []

        for k, p in self.pred_function_module.get_etas().items() :
            parameters.append(p)
        
        for k, p in self.pred_function_module.get_epss().items() :
            parameters.append(p)
        
        return parameters

    def fit_population(self, checkpoint_file_path : Optional[str] = None, learning_rate : float= 1, tolerance_grad = 1e-2, tolerance_change = 1e-2, max_iteration = 1000,):
        max_iter = max_iteration
        parameters = self.parameters()
        self.pred_function_module.reset_epss()
        optimizer = tc.optim.LBFGS(parameters, 
                                   max_iter = max_iter, 
                                   lr = learning_rate, 
                                   tolerance_grad = tolerance_grad, 
                                   tolerance_change = tolerance_change)
        opt_fn = self.optimization_function(self.pred_function_module.dataset, optimizer, checkpoint_file_path = checkpoint_file_path)
        optimizer.step(opt_fn)
        return self
    
    def fit_individual(self, checkpoint_file_path : Optional[str] = None, learning_rate = 1, tolerance_grad = 1e-2, tolerance_change = 3e-2, max_iteration = 1000,):
        max_iter = max_iteration
        parameters = self.parameters_for_individual()
        optimizer = tc.optim.LBFGS(parameters, 
                                   max_iter = max_iter, 
                                   lr = learning_rate, 
                                   tolerance_grad = tolerance_grad, 
                                   tolerance_change = tolerance_change)
        opt_fn = self.optimization_function(self.pred_function_module.dataset, optimizer, checkpoint_file_path = checkpoint_file_path)
        optimizer.step(opt_fn)
   
    def covariance_step(self) :

        dataset = self.pred_function_module.dataset

        theta_dict = self.pred_function_module.get_theta_parameter_values()

        cov_mat_dim =  len(theta_dict)
        for tensor in self.omega.parameter_values :
            cov_mat_dim += tensor.size()[0]
        for tensor in self.sigma.parameter_values :
            cov_mat_dim += tensor.size()[0]
        
        thetas = [theta_dict[key] for key in self.theta_names]

        estimated_parameters = [*thetas,
                        *self.omega.parameter_values,
                        *self.sigma.parameter_values]
 
        r_mat = tc.zeros(cov_mat_dim, cov_mat_dim, device=dataset.device)
 
        s_mat = tc.zeros(cov_mat_dim, cov_mat_dim, device=dataset.device)

        dataloader = tc.utils.data.DataLoader(dataset, batch_size=None, shuffle=False, num_workers=0)
 
        for data, y_true in dataloader:
            
            y_pred, eta, eps, g, h, omega, sigma, mdv_mask, _ = self(data)

            id = str(int(data[:,self.pred_function_module._column_names.index('ID')][0]))
            print('id', id)
 
            y_pred = y_pred.masked_select(mdv_mask)

            if eta.size()[-1] > 0 :
                g = g.t().masked_select(mdv_mask).reshape((eta.size()[-1],-1)).t()
            
            if eps.size()[0] > 0 :
                h = h.t().masked_select(mdv_mask).reshape((eps.size()[0],-1)).t()
 
            y_true_masked = y_true.masked_select(mdv_mask)
            loss = self.objective_function(y_true_masked, y_pred, g, h, eta, omega, sigma)            

            gr = tc.autograd.grad(loss, estimated_parameters, create_graph=True, retain_graph=True, allow_unused=True)
            gr = [grad.unsqueeze(0) if grad.dim() == 0 else grad for grad in gr]
            gr_cat = tc.concat(gr, dim=0)
            
            with tc.no_grad() :
                s_mat.add_((gr_cat.detach().unsqueeze(1) @ gr_cat.detach().unsqueeze(0))/4)
            
            for i, gr_cur in enumerate(gr_cat) :
                hs = tc.autograd.grad(gr_cur, estimated_parameters, create_graph=True, retain_graph=True, allow_unused=True)

                hs = [grad.unsqueeze(0) if grad.dim() == 0 else grad for grad in hs]
                hs_cat = tc.cat(hs)
                for j, hs_elem in enumerate(hs_cat) :
                    r_mat[i,j] = r_mat[i,j] + hs_elem.detach()/2

        invR = r_mat.inverse()
        
        cov = invR @ s_mat @ invR
        
        se = cov.diag().sqrt()
        
        correl = covariance_to_correlation(cov)
        
        # ei_values, ei_vectors = correl.symeig(eigenvectors=False)

        ei_values, ei_vectors = tc.linalg.eigh(correl)

        ei_values_sorted, _ = ei_values.sort()
        inv_cov = r_mat @ s_mat.inverse() @ r_mat
        
        return {'cov': cov, 'se': se, 'cor': correl, 'ei_values': ei_values_sorted , 'inv_cov': inv_cov, 'r_mat': r_mat, 's_mat':s_mat}
        # return {'cov': cov, 'se': se, 'cor': correl, 'inv_cov': inv_cov, 'r_mat': r_mat, 's_mat':s_mat}

    #TODO 경고, simulation 사용하면 안에 들어있던 eta데이터 덮어 씌움
    def simulate(self, dataset : CSVDataset, repeat : int) :
        """
        simulationg
        Args:
            dataset: model dataset for simulation
            repeat : simulation times
        """
        omega = self.omega()
        sigma = self.sigma()


        eta_names = list(itertools.chain(*self.eta_names))
        eta_parameter_values = self.pred_function_module.get_eta_parameter_values()
        eta_size = len(eta_parameter_values)
        mvn_eta = tc.distributions.multivariate_normal.MultivariateNormal(tc.zeros(eta_size, device=dataset.device), omega)
        etas = mvn_eta.rsample(tc.tensor((len(dataset), repeat), device=dataset.device))

        eps_names = list(itertools.chain(*self.eps_names))
        eps_parameter_values = self.pred_function_module.get_eps_parameter_values()
        eps_size = len(eps_parameter_values)
        mvn_eps = tc.distributions.multivariate_normal.MultivariateNormal(tc.zeros(eps_size, device=dataset.device), sigma)
        epss = mvn_eps.rsample(tc.tensor([len(dataset), repeat, self.pred_function_module._max_record_length], device=dataset.device))

        dataloader = tc.utils.data.DataLoader(dataset, batch_size=None, shuffle=False, num_workers=0)

        etas_result : Dict[str, tc.Tensor] = {}
        epss_result : Dict[str, tc.Tensor] = {}
        preds : Dict[str, List[tc.Tensor]] = {}
        times : Dict[str, tc.Tensor] = {}
        output_columns : Dict[str, List[Dict[str, tc.Tensor]]] = {}
 
        for i, (data, _) in enumerate(dataloader):
            
            id = str(int(data[:, self.pred_function_module._column_names.index('ID')][0]))
            
            etas_cur = etas[i,:,:]
            epss_cur = epss[i,:,:]

            time_data = data[:,self.pred_function_module._column_names.index('TIME')].t()

            times[id] = time_data
            etas_result[id] = etas_cur
            epss_result[id] = epss_cur
            preds[id] = []
            output_columns[id] = []

            for repeat_iter in range(repeat) :

                with tc.no_grad() :
                    eta_value = etas_cur[repeat_iter]
                    eps_value = epss_cur[repeat_iter]

                    for eta_i, name in enumerate(eta_names) :
                        eta_parameter_values[name].update({str(int(id)): tc.nn.Parameter(eta_value[eta_i])})

                    for eps_i, name in enumerate(eps_names) :
                        eps_parameter_values[name].update({str(int(id)): tc.nn.Parameter(eps_value[:data.size()[0],eps_i])})

                    r  = self.pred_function_module(data)
                    y_pred = r['y_pred']

                    preds[id].append(y_pred)
                    output_columns[id].append(r['output_columns'])

        return {'times': times, 'preds': preds, 'etas': etas_result, 'epss': epss_result, 'output_columns': output_columns}