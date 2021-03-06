import unittest
import torch as tc
from torch import nn
from torchpm import covariate, odesolver, predfunction, models, loss
from torchpm import data
from torchpm.data import CSVDataset
from torchpm.parameter import *
import matplotlib.pyplot as plt
import numpy as np

if __name__ == '__main__' :
    unittest.main()

class ShowTimeDVTest(unittest.TestCase):
    def test_show_time_dv(self):
        dataset_file_path = './examples/THEO.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)
        column_names = ['ID', 'AMT', 'TIME', 'DV', 'CMT', "MDV", "RATE", 'BWT']
        dataset = CSVDataset(dataset_np, column_names)

        for data, y_true in dataset:
            time = data.t()[column_names.index('TIME')]
            
        
            fig = plt.figure()   
            ax = fig.add_subplot(1, 1, 1)             
            ax.plot(time, y_true, color="black")
            plt.show()


class FisherInformationMatrixTest(unittest.TestCase):
    def test_fisher_information_matrix(self):
        dataset_file_path = './examples/THEO.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)

        device = tc.device("cuda:0" if tc.cuda.is_available() else "cpu")
        column_names = ['ID', 'AMT', 'TIME', 'DV', 'CMT', "MDV", "RATE", 'BWT']
        dataset = CSVDataset(dataset_np, column_names, device)
        
        output_column_names=['ID', 'TIME', 'AMT', 'k_a', 'v', 'k_e']

        omega = Omega([0.1, 0.1, 0.1], [True])
        sigma = Sigma([0.1], [True])

        



        print('=================================== A Optimal ===================================')
        model = models.FOCEInter(dataset = dataset,
                                output_column_names= output_column_names,
                                pred_function = BasementModelFIM, 
                                theta_names=['theta_0', 'theta_1', 'theta_2'],
                                eta_names= ['eta_0', 'eta_1','eta_2'], 
                                eps_names= ['eps_0'], 
                                omega=omega, 
                                sigma=sigma,
                                optimal_design_creterion=loss.AOptimality()).to(device)

        model.fit_population_FIM(model.parameters())

        print('=================================== A Optimal, omega, sigma ===================================')

        model = model.descale()
        parameters = [*model.omega.parameter_values, *model.sigma.parameter_values]
        model.fit_population_FIM(parameters)
        


        for p in model.descale().named_parameters():
            print(p)

        print('=================================== Adam ===================================')

        parameters = [*model.omega.parameter_values, *model.sigma.parameter_values]
        # parameters = model.parameters()
        optimizer = tc.optim.Adam(parameters, lr=0.001)

        for i in range(100):
            model.optimization_function_FIM(optimizer)
            optimizer.step()
        

        model = model.descale()

        eval_fim_values, loss_value = model.evaluate_FIM()
        print(loss_value)
        for k, v in eval_fim_values.items():
            print(k)
            print(v)

        # eval_values = model.evaluate()
        # for k, v in eval_values.items():
        #     print(k)
        #     print(v)

        for p in model.descale().named_parameters():
            print(p)

        print(model.descale().covariance_step())

        tc.manual_seed(42)
        simulation_result = model.simulate(dataset, 300)

        i = 0
        fig = plt.figure()

        for id, values in simulation_result.items() :
            i += 1
            ax = fig.add_subplot(12, 1, i)
            print('id', id)
            time_data : tc.Tensor = values['time'].to('cpu')
            
            preds : List[tc.Tensor] = values['preds']
            preds_tensor = tc.stack(preds).to('cpu')
            p95 = np.percentile(preds_tensor, 95, 0)
            p50 = np.percentile(preds_tensor, 50, 0)
            average = np.average(preds_tensor, 0)
            p5 = np.percentile(preds_tensor, 5, 0)
            
            ax.plot(time_data, p95, color="black")
            ax.plot(time_data, p50, color="green")
            ax.plot(time_data, average, color="red")
            ax.plot(time_data, p5, color="black")

            for y_pred in values['preds'] :
                ax.plot(time_data, y_pred.detach().to('cpu'), marker='.', linestyle='', color='gray')
        plt.show()

"""
    Args:.
    Attributes: .
"""
class LinearODETest(unittest.TestCase) :
    def setUp(self):
        pass
    
    def tearDown(self):
        pass

    
    def test_infusion(self):
        dist_mat = [[True]]
        model = odesolver.CompartmentModelGenerator(dist_mat, is_infusion=True)
        d = tc.tensor(320.)
        t = tc.range(0,24,0.05)
        k_00 = tc.tensor(1.)
        r = tc.tensor(160.)
        result = model(t=t, k_00=k_00, d=d, r=r)
        print(t)
        print(result)
        print('time-pred')
        fig = plt.figure()
        ax = fig.add_subplot(1, 1, 1)
        ax.plot(t.to('cpu'), result[0].detach().to('cpu').numpy())
        plt.show()

    def test_gut(self):
        model = odesolver.CompartmentModelGenerator([[True]], has_depot=True, transit = 3, is_infusion=False)
        dose = tc.tensor(320.)
        t = tc.arange(0., 24., step=0.1)
        k00 = tc.tensor(1.5)
        k12 = tc.tensor(0.6)
        k23 = tc.tensor(0.7)
        k34 = tc.tensor(0.8)
        k_administrated = tc.tensor(0.2)
        result = model(t=t, k_00= k00, k_12 = k12, k_23 = k23, k_34 = k34, k_40 = k_administrated, d=dose)
        print(t)
        print(result)
        fig = plt.figure()
        ax = fig.add_subplot(1, 1, 1)
        ax.plot(t.to('cpu'), result[0].detach().to('cpu').numpy())
        plt.show()

class BasementModel(predfunction.PredictionFunctionByTime) :

    def _set_estimated_parameters(self):
        self.theta_0 = Theta(0., 5., 10.)
        self.theta_1 = Theta(0., 30., 100.)
        self.theta_2 = Theta(0, 0.08, 1)

        self.eta_0 = Eta()
        self.eta_1 = Eta()
        self.eta_2 = Eta()

        self.eps_0 = Eps()
        self.eps_1 = Eps()
    
    def _calculate_parameters(self, para):
        para['k_a'] = self.theta_0()*tc.exp(self.eta_0())
        para['v'] = self.theta_1()*tc.exp(self.eta_1())
        para['k_e'] = self.theta_2()*tc.exp(self.eta_2())
        para['AMT'] = tc.tensor(320., device=self.dataset.device)

    def _calculate_preds(self, t, p):
        dose = p['AMT'][0]
        k_a = p['k_a']
        v = p['v']
        k_e = p['k_e']
        return  (dose / v * k_a) / (k_a - k_e) * (tc.exp(-k_e*t) - tc.exp(-k_a*t))
        
    def _calculate_error(self, y_pred, p):
        p['v_v'] = p['v'] 
        return y_pred +  y_pred * self.eps_0() + self.eps_1()

class BasementModelFIM(predfunction.PredictionFunctionByTime) :

    def _set_estimated_parameters(self):
        self.theta_0 = Theta(0.01, 2., 10.)
        self.theta_1 = Theta(0.01, 30., 40.)
        self.theta_2 = Theta(0.01, 0.8, 1.)

        self.eta_0 = Eta()
        self.eta_1 = Eta()
        self.eta_2 = Eta()

        self.eps_0 = Eps()
    
    def _calculate_parameters(self, para):
        para['k_a'] = self.theta_0() * self.eta_0().exp()
        para['v'] = self.theta_1() * self.eta_1().exp()
        para['k_e'] = self.theta_2() * self.eta_2().exp()
        para['AMT'] = tc.tensor(320., device=self.dataset.device)

    def _calculate_preds(self, t, p):
        dose = p['AMT'][0]
        k_a = p['k_a']
        v = p['v']
        k_e = p['k_e']
        return  (dose / v * k_a) / (k_a - k_e) * (tc.exp(-k_e*t) - tc.exp(-k_a*t))
        
    def _calculate_error(self, y_pred, p):
        p['v_v'] = p['v'] 
        return y_pred +  self.eps_0()


class AnnModel(predfunction.PredictionFunctionByTime) :
    '''
        pass
    '''
    def _set_estimated_parameters(self):
        self.theta_0 = Theta(0., 1.5, 10.)
        self.theta_1 = Theta(0., 30., 100.)
        self.theta_2 = Theta(0, 0.08, 1)

        self.eta_0 = Eta()
        self.eta_1 = Eta()
        self.eta_2 = Eta()

        self.eps_0 = Eps()
        self.eps_1 = Eps()

        self.lin = nn.Sequential(nn.Linear(1,3),
                                    nn.Linear(3,3))
    
    def _calculate_parameters(self, para):
        
        lin_r = self.lin(para['BWT'].unsqueeze(-1)/70).t() 
        para['k_a'] = self.theta_0()*tc.exp(self.eta_0()+lin_r[0])
        para['v'] = self.theta_1()*tc.exp(self.eta_1()+lin_r[1])
        para['k_e'] = self.theta_2()*tc.exp(self.eta_2()+lin_r[2])
        para['AMT'] = tc.tensor(320., device=self.dataset.device)

        

    def _calculate_preds(self, t, p):
        dose = p['AMT'][0]
        k_a = p['k_a']
        v = p['v']
        k_e = p['k_e']
        return  (dose / v * k_a) / (k_a - k_e) * (tc.exp(-k_e*t) - tc.exp(-k_a*t))
        
    def _calculate_error(self, y_pred, p):
        p['v_v'] = p['v'] 
        return y_pred +  y_pred * self.eps_0() + self.eps_1()





class AmtModel(predfunction.PredictionFunctionByTime) :

    def _set_estimated_parameters(self):

        self.theta_0 = Theta(0, 100, 500)

        self.eta_0 = Eta()
        self.eta_1 = Eta()
        self.eta_2 = Eta()

        self.eps_0 = Eps()
        self.eps_1 = Eps()
        
    def _calculate_parameters(self, para):
        para['k_a'] = 1.4901*tc.exp(self.eta_0())
        para['v'] = 32.4667*tc.exp(self.eta_1())
        para['k_e'] = 0.0873*tc.exp(self.eta_2())
        para['AMT'] = para['AMT']*self.theta_0()

    def _calculate_preds(self, t, para):
        dose = para['AMT'][0]
        k_a = para['k_a'] 
        v = para['v']
        k = para['k_e']
        
        return (dose / v * k_a) / (k_a - k) * (tc.exp(-k*t) - tc.exp(-k_a*t))
    
    def _calculate_error(self, y_pred, para) :
        return y_pred +  y_pred * self.eps_0() + self.eps_1()

class ODEModel(predfunction.PredictionFunctionByODE) :
    def _set_estimated_parameters(self):
        self.theta_0 = Theta(0., 1.5, 10)
        self.theta_1 = Theta(0, 30, 100)
        self.theta_2 = Theta(0, 0.08, 1)

        self.eta_0 = Eta()
        self.eta_1 = Eta()
        self.eta_2 = Eta()

        self.eps_0 = Eps()
        self.eps_1 = Eps()
    
    def _calculate_parameters(self, p):
        p['k_a'] = self.theta_0()*tc.exp(self.eta_0())
        p['v'] = self.theta_1()*tc.exp(self.eta_1())*p['COV']
        p['k_e'] = self.theta_2()*tc.exp(self.eta_2())
    
    def _calculate_preds(self, t, y, p) -> tc.Tensor :
        mat = tc.zeros(2,2, device=y.device)
        mat[0,0] = -p['k_a']
        mat[1,0] = p['k_a']
        mat[1,1] = -p['k_e']
        return mat @ y

    def _calculate_error(self, y_pred: tc.Tensor, parameters: Dict[str, tc.Tensor]) -> tc.Tensor:
        y = y_pred/parameters['v']
        return y +  y * self.eps_0() + self.eps_1()
        
class TotalTest(unittest.TestCase) :

    def setUp(self):
        pass
    def tearDown(self):
        pass
    
    def test_basement_model(self):
        dataset_file_path = './examples/THEO.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)

        device = tc.device("cuda:0" if tc.cuda.is_available() else "cpu")
        column_names = ['ID', 'AMT', 'TIME', 'DV', 'CMT', "MDV", "RATE", 'BWT']
        dataset = CSVDataset(dataset_np, column_names, device)
        
        output_column_names=['ID', 'TIME', 'AMT', 'k_a', 'v', 'k_e']

        omega = Omega([0.4397,
                        0.0575,  0.0198, 
                        -0.0069,  0.0116,  0.0205], False, requires_grads=False)
        sigma = Sigma([[0.0177], [0.0762]], [True, True], requires_grads=[False, True])

        model = models.FOCEInter(dataset = dataset,
                                output_column_names= output_column_names,
                                pred_function = BasementModel, 
                                theta_names=['theta_0', 'theta_1', 'theta_2'],
                                eta_names= ['eta_0', 'eta_1','eta_2'], 
                                eps_names= ['eps_0','eps_1'], 
                                omega=omega, 
                                sigma=sigma)
                                
        model = model.to(device)
        model.fit_population(learning_rate = 1, tolerance_grad = 1e-5, tolerance_change= 1e-3)

        eval_values = model.evaluate()
        for k, v in eval_values.items():
            print(k)
            print(v)

        for p in model.descale().named_parameters():
            print(p)

        print(model.descale().covariance_step())

        tc.manual_seed(42)
        simulation_result = model.simulate(dataset, 300)

        i = 0
        

        for id, values in simulation_result.items() :
            fig = plt.figure()
            # i += 1
            ax = fig.add_subplot(1, 1, 1)
            print('id', id)
            time_data : tc.Tensor = values['time'].to('cpu')
            
            preds : List[tc.Tensor] = values['preds']
            preds_tensor = tc.stack(preds).to('cpu')
            p95 = np.percentile(preds_tensor, 95, 0)
            p50 = np.percentile(preds_tensor, 50, 0)
            average = np.average(preds_tensor, 0)
            p5 = np.percentile(preds_tensor, 5, 0)
            
            ax.plot(time_data, p95, color="black")
            ax.plot(time_data, p50, color="green")
            ax.plot(time_data, average, color="red")
            ax.plot(time_data, p5, color="black")

            for y_pred in values['preds'] :
                ax.plot(time_data, y_pred.detach().to('cpu'), marker='.', linestyle='', color='gray')
            
            plt.show()
    
    def test_ANN_model(self):
        dataset_file_path = './examples/THEO.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)

        device = tc.device("cuda:0" if tc.cuda.is_available() else "cpu")
        column_names = ['ID', 'AMT', 'TIME', 'DV', 'CMT', "MDV", "RATE", 'BWT']
        dataset = CSVDataset(dataset_np, column_names, device)
        
        output_column_names=['ID', 'TIME', 'AMT', 'k_a', 'v', 'k_e']

        omega = Omega([0.4397,
                        0.0575,  0.0198, 
                        -0.0069,  0.0116,  0.0205], False, requires_grads=False)
        sigma = Sigma([[0.0177], [0.0762]], [True, True], requires_grads=[False, True])

        model = models.FOCEInter(dataset = dataset,
                                output_column_names= output_column_names,
                                pred_function = AnnModel, 
                                theta_names=['theta_0', 'theta_1', 'theta_2'],
                                eta_names= ['eta_0', 'eta_1','eta_2'], 
                                eps_names= ['eps_0','eps_1'], 
                                omega=omega, 
                                sigma=sigma)
                                
        model = model.to(device)
        model.fit_population(learning_rate = 1, tolerance_grad = 1e-5, tolerance_change= 1e-3)
    
    def test_pred_amt(self):
        dataset_file_path = './examples/THEO_AMT.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)


        column_names = ['ID', 'AMT', 'TIME',    'DV',   'BWT', 'CMT', "MDV", "tmpcov", "RATE"]
        
        device = tc.device("cuda:0" if tc.cuda.is_available() else "cpu")
        dataset = CSVDataset(dataset_np, column_names, device)

        output_column_names=column_names+['k_a', 'v', 'k_e']
        omega = Omega([[0.4397,
                        0.0575,  0.0198, 
                        -0.0069,  0.0116,  0.0205]], [False], requires_grads=True)
        sigma = Sigma([0.0177, 0.0762], [True])

        model = models.FOCEInter(dataset=dataset,
                                output_column_names=output_column_names,
                                pred_function = AmtModel, 
                                theta_names=['theta_0'],
                                eta_names=['eta_0', 'eta_1','eta_2'], 
                                eps_names= ['eps_0','eps_1'], 
                                omega=omega, 
                                sigma=sigma)
        
        model = model.to(device)
        model.fit_population(learning_rate = 1, tolerance_grad = 1e-3, tolerance_change= 1e-3)

        eval_values = model.evaluate()
        for id, values in eval_values.items():
            print(id)
            for k, v in values.items() :
                print(k)
                print(v)

        for p in model.descale().named_parameters():
            print(p)


    def test_ODE(self):

        dataset_file_path = './examples/THEO_ODE.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)

        column_names = ['ID', 'TIME', 'AMT', 'RATE', 'DV', 'MDV', 'CMT', 'COV']

        device = tc.device("cpu")
        dataset = CSVDataset(dataset_np, column_names, device)
        output_column_names=column_names+['k_a', 'v', 'k_e']

        omega = Omega([[0.4397,
                        0.0575,  0.0198, 
                        -0.0069,  0.0116,  0.0205]], [False], requires_grads=True)
        sigma = Sigma([[0.0177, 0.0762]], [True])

        model = models.FOCEInter(dataset=dataset,
                                output_column_names=output_column_names,
                                pred_function = ODEModel, 
                                theta_names = ['theta_0', 'theta_1', 'theta_2'],
                                eta_names=['eta_0', 'eta_1','eta_2'], 
                                eps_names= ['eps_0','eps_1'], 
                                omega=omega, 
                                sigma=sigma)
        
        model = model.to(device)
        model.fit_population(learning_rate = 1, tolerance_grad = 1e-1, tolerance_change= 1e-2)

        for p in model.descale().named_parameters():
            print(p)

        print(model.descale().covariance_step())

        eval_values = model.descale().evaluate()
        for id, values in eval_values.items() :
            print(id)
            for k, v in values.items() :
                print(k)
                print(v)
    
    def test_covariate_model(self) :
        def function(para):
            value = para['v_theta']()*tc.exp(para['v_eta']())*para['BWT']/70
            return {'v': value}
        cov = covariate.Covariate(['v'],[[0,32,50]],['BWT'],function)

        cov_model_decorator = covariate.CovariateModelDecorator([cov])
        CovModel = cov_model_decorator(BasementModel)
        
        dataset_file_path = './examples/THEO.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)

        device = tc.device("cuda:0" if tc.cuda.is_available() else "cpu")
        column_names = ['ID', 'AMT', 'TIME', 'DV', 'CMT', "MDV", "RATE", 'BWT']
        dataset = CSVDataset(dataset_np, column_names, device)
        output_column_names=['ID', 'TIME', 'AMT', 'k_a', 'v', 'k_e']

        omega = Omega([0.4397,
                        0.0575,  0.0198, 
                        -0.0069,  0.0116,  0.0205], False, requires_grads=True)
        sigma = Sigma([[0.0177], [0.0762]], [True, True], requires_grads=[True, True])

        model = models.FOCEInter(dataset=dataset,
                                output_column_names=output_column_names,
                                pred_function=CovModel, 
                                theta_names=['theta_0', 'v_theta', 'theta_2'],
                                eta_names= ['eta_0', 'v_eta','eta_2'], 
                                eps_names= ['eps_0','eps_1'], 
                                omega=omega, 
                                sigma=sigma)
                                
        model = model.to(device)
        model.fit_population(learning_rate = 1, tolerance_grad = 1e-2, tolerance_change= 1e-3)
    
    def test_covariate_ann_model(self) :
            
        dataset_file_path = './examples/THEO_cov_searching.csv'
        dataset_np = np.loadtxt(dataset_file_path, delimiter=',', dtype=np.float32, skiprows=1)
        device = tc.device("cuda:0" if tc.cuda.is_available() else "cpu")
        column_names = ['ID', 'AMT', 'TIME', 'DV', 'CMT', "MDV", "RATE", 'BWT', 'fixed', 'rand-1+1', 'norm(0,1)', 'BWT-0.5+0.5']
        dataset = CSVDataset(dataset_np, column_names, device)
        
        dependent_parameter_names = ['k_a', 'v', 'k_e']
        dependent_parameter_initial_values = [[0,1.4901,2],[30,32.4667,34],[0,0.08,0.1]]
        independent_parameter_names = ['BWT', 'fixed', 'rand-1+1', 'norm(0,1)', 'BWT-0.5+0.5']

        searcher = covariate.DeepCovariateSearching(dataset=dataset,
                                        BaseModel=BasementModel,
                                        dependent_parameter_names=dependent_parameter_names,
                                        independent_parameter_names=independent_parameter_names,
                                        dependent_parameter_initial_values=dependent_parameter_initial_values,
                                        eps_names=['eps_0', 'eps_1'],
                                        omega = Omega([0.4397,
                                                        0.0575,  0.0198, 
                                                        -0.0069,  0.0116,  0.0205], False, requires_grads=True),
                                        sigma = Sigma([[0.0177], [0.0762]], [True, True], requires_grads=[True, True]))
        r = searcher.run(tolerance_grad=1e-3, tolerance_change=1e-3)
        history = r['history']
        for record in history :
            print(record)