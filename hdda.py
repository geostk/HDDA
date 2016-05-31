# -*- coding: utf-8 -*-
import scipy as sp
from scipy import linalg
from sklearn.cross_validation import StratifiedKFold
from sklearn.cluster import KMeans
import accuracy_index as ai

## Numerical precision
EPS = sp.finfo(sp.float64).eps
MAX = sp.finfo(sp.float64).max

## Empirical estimators for EM
def soft_cov(x,m,ti,ni):
    """
    This function implements a soft estimation of the covariance function. It is used in the EM iterations
    """
    n,d=x.shape
    ti_ = sp.copy(ti).reshape(n,1)
    # Center the data
    xc = x-m

    # Compute the soft covariance matrix using <X.T,X>
    return sp.dot(xc.T,xc*ti_)/(ni-1)

## HDDA Class
class HDGMM():
    """
    This class implements the HDDA models proposed by Charles Bouveyron and Stephane Girard
    Details about methods can be found here:
    http://w3.mi.parisdescartes.fr/~cbouveyr/
    """
    def __init__(self,model='M1'):
        """
        This function initialize the HDDA stucture
        :param model: the model used.
        :type mode: string
        - M1 = aijbiQidi
        - M2 = aijbiQid
        - M3 = aijbQidi
        - M4 = aijbQid
        - M5 = aibiQidi
        - M6 = aibiQid
        - M7 = aibQidi
        - M8 = aibQid
        - M9 = abiQidi <--
        - M10 = abiQid
        - M11 = abQidi
        - m12 = abQid
        """
        self.ni = []          # Number of samples of each class
        self.prop = []        # Proportion of each class
        self.mean = []        # Mean vector
        self.cov = []         # Covariance matrix
        self.pi=[]            # Signal subspace size
        self.L = []           # Eigenvalues of covariance matrices
        self.Q = []           # Eigenvectors of covariance matrices
        self.trace = []       # Trace of the covariance matrices
        self.a = []           # Eigenvalues of signal subspaces
        self.b = []           # Values of the noise
        self.logdet = []      # Pre-computation of the logdet of covariance matrices using HDDA models
        self.model=model      # Name of the model
        self.q = []           # Number of parameters of the full models
        self.bic = []         # bic values over the iterations
        self.niter = None     # Number of iterations

    def free(self,full=False):
        """This  function free some  parameters of the  model. It is  used to
        speed-up the cross validation process.
        
        :param full: To free only the parcimonious part or all the model
        :type full: bool
        """
        self.pi=[]
        self.a = []
        self.b = []
        self.logdet = []
        self.q = []
               
        if full:
            self.ni = []          # Number of samples of each class
            self.prop = []        # Proportion of each class
            self.mean = []        # Mean vector
            self.cov = []         # Covariance matrix
            self.pi=[]            # Signal subspace size
            self.L = []           # Eigenvalues of covariance matrices
            self.Q = []
            self.trace = []
        
    def fit(self,x,y=None,param=None):
        """
        This function fit the HDDA model

        :param x: The sample matrix, is of size x \times d where n is the number of samples and d is the number of variables
        :param y: The vector of corresponding labels, is of size n \times 1 in the supervised case, otherwise it is None
        :param param: A dictionnary of parameters. For the supervised case, it contains the threshold or the size of the signal subspace. For the unsupervised case, it contains also the number of classes and the initialization method.
        :type x: float
        :type y: int
        :type param: dictionnary
        :return: the predicted label for the unsupervised case
        """
        EM = False
        n,d = x.shape

        # Set defaults parameters
        default_param={'th':0.9,'init':'kmeans','itermax':100,'tol':0.001,'C':4,'population':2,'random_state':0}
        for key,value in default_param.iteritems():
            if not param.has_key(key):
                param[key]=value
                
        # If unsupervised case
        if y is None: # Initialisation of the class membership
            init = param['init']
            EM,ITER,ITERMAX,TOL,LL = True,0,param['itermax'],param['tol'],[]
            if init is 'kmeans':
                y = KMeans(n_clusters=param['C'],n_init=10,n_jobs=-1,random_state=param['random_state']).fit_predict(x)
                # Check for minimal size of cluster
                nc = sp.asarray([len(sp.where(y==i)[0]) for i in xrange(param['C'])])
                if sp.any(nc<2):
                    self.LL,self.bic,self.icl,self.niter = LL, MAX, MAX, (ITER+1)
                    return None
                else:
                    y += 1 # Label starts at one
            elif init is 'random':
                sp.random.seed(param['random_state'])
                y = sp.random.randint(1,high=param['C']+1,size=n)
                
        # Initialization of the parameter
        self.fit_init(x,y)
        self.fit_update(param)
        ll,K = self.loglike(x)
        LL.append(ll)
        if EM is True: # Unsupervised case, needs iteration
            while(ITER<ITERMAX):
                # E step - Use the precomputed K
                T = sp.empty_like(K)
                for c in xrange(param['C']):
                    T[:,c] = 1 / sp.exp(0.5*(K[:,c].reshape(n,1)-K)).sum(axis=1)
                    
                # Check for empty classes
                if sp.any(T.sum(axis=0)<param['population']): # If empty return infty bic
                    self.LL,self.bic,self.icl,self.niter = LL, MAX, MAX, (ITER+1)
                    return None
                
                # M step
                self.free(full=True)
                self.fit_init(x,T)
                self.fit_update(param)

                # Compute the BIC and do the E step
                ll,K=self.loglike(x)
                LL.append(ll)
                if abs((LL[-1]-LL[-2])/LL[-2]) <TOL:
                    break
                else:
                    ITER += 1

            # Compute the membership
            T = sp.empty_like(K)
            for c in xrange(param['C']):
                T[:,c] = 1 / sp.exp(0.5*(K[:,c].reshape(n,1)-K)).sum(axis=1)
            
            # Return the class membership and some parameters of the optimization
            self.LL = LL
            self.bic = -2*LL[-1]+ self.q*sp.log(n)
            self.icl = self.bic + 2*(T*sp.log(T+EPS)).sum()
            self.niter = ITER + 1
           
            return sp.argmax(T)+1 
                
    def predict(self,xt,out=None):
        """
        This function compute the decision of the fitted HD model.
        :param xt: The samples matrix of testing samples
        :param out: Setting to a value different from None will let the function returns the posterior probability for each class.
        :type xt: float
        :type out: string
        :return yp: The predicted labels and posterior probabilities if asked.
        """
        nt,d = xt.shape
        C = len(self.a)
        K = sp.empty((nt,C))
        
        ## Start the prediction for each class
        for c in xrange(C):
            # Compute the constant term
            cst = self.logdet[c] - 2*sp.log(self.prop[c]) + d*sp.log(2*sp.pi)
            # Remove the mean
            xtc = xt-self.mean[c]
            # Do the projection
            P = sp.dot(self.Q[c],self.Q[c].T)
            Px = sp.dot(xtc,P)
            temp = sp.dot(Px,self.Q[c]/sp.sqrt(self.a[c]))
            K[:,c] = sp.sum(temp**2,axis=1) + sp.sum((xtc - Px)**2,axis=1)/self.b[c] + cst
        
        ## Assign the label to the minimum value of K 
        if out is None:
            yp = sp.argmin(K,1)+1
            return yp
        elif out is 'proba':
            for c in xrange(C):
                K[:,c] += 2*sp.log(self.prop[c])
            K *= -0.5
            return yp,K
        elif out is 'ki':
            return K        

    def fit_init(self,x,y):
        """This  function computes  the  empirical  estimators of  the  mean
        vector,  the convariance  matrix  and the  proportion of  each
        class.
        :param x: The sample matrix, is of size x \times d where n is the number of samples and d is the number of variables
        :param y: The vector of corresponding labels, is of size n \times 1 in the supervised case and n \times C in the unsupervised case
        :type x: float
        :type y: int
        """
        ## Get information from the data
        n,d = x.shape    # Number of samples and number of variables
        if y.ndim == 1:  # Number of classes
            C = int(y.max(0))   
        else:
            C = y.shape[1]
        
        if n != y.shape[0]:
            print("size of x and y should match")
            exit()
            
        ## Compute the whole covariance matrix
        self.W = sp.cov(x,rowvar=0)
        
        ## Learn the empirical of the model for each class
        for c in xrange(C):
            if y.ndim == 1: # Supervised case
                j = sp.where(y==(c+1))[0]
                self.ni.append(j.size)
                self.prop.append(float(self.ni[c])/n)
                self.mean.append(sp.mean(x[j,:],axis=0))
                cov = sp.cov(x[j,:],rowvar=0)
            else: # Unsupervised case
                self.ni.append(y[:,c].sum())
                self.prop.append(float(self.ni[c])/n)
                self.mean.append(sp.average(x,weights=y[:,c],axis=0))
                cov = soft_cov(x,self.mean[c],y[:,c],self.ni[c])
                
            self.cov.append(cov)
            if int(self.ni[c]>=d): # Check if the covariance matrix is full rank
                L,Q = linalg.eigh(cov)
            else: # If not, compute only the ni first eigenvalues/eigenvectors
                L,Q = linalg.eigh(cov,eigvals=(d-int(self.ni[c]),d-1)) 
            idx = L.argsort()[::-1]
            L,Q = L[idx],Q[:,idx]
            L[L<EPS]=EPS # Chek for numerical errors
            self.L.append(L)
            self.Q.append(Q)
            self.trace.append(cov.trace())

    def fit_update(self,param):
        """
        This function compute the parcimonious HDDA model from the empirical estimates obtained with fit_init
        """
        C = len(self.ni)
        d = self.mean[0].size

        # Get parameters
        th = param['th']

        # For common size subspace models
        if self.model in ('M2','M4','M6','M8'):
            # Compute intrinsic dimension on the whole data set
            if int(min(self.ni)>=d):  # Check if the covariance matrix of the class with the smallest size is full rank
                L = linalg.eigh(self.W,eigvals_only=True)
            else:
                L = linalg.eigh(self.W,eigvals_only=True,eigvals=(d-int(min(self.ni)),d-1))
            idx = L.argsort()[::-1]
            L = L[idx]
            L[L<EPS]=EPS # Chek for numerical errors
            dL,p = sp.absolute(sp.diff(L)),0
            dL /= dL.max()
            while sp.any(dL[p:]>th):
                p += 1
            p += 1 # To take into account python broadcasting a[:p] = a[0]...a[p-1]
            
        for c in xrange(C):
            # Estimation of the signal subspace
            if self.model in ('M1','M3','M5','M7'):
                # Scree test
                dL,pi = sp.absolute(sp.diff(self.L[c])),0
                dL /= dL.max()
                while sp.any(dL[pi:]>th):
                    pi += 1
                pi += 1
                
            elif self.model in ('M2','M4','M6','M8'):
                pi = p
            if pi >= d:
                pi -= 1
                
            self.pi.append(pi)
            
        if self.model in ('M1','M2','M5','M6'): # Noise free
            for c in xrange(C):
                # Estim signal part
                self.a.append(self.L[c][:self.pi[c]])
                if self.model in ('M5','M6'):
                    self.a[c][:] = self.a[c][:].mean()
                 # Estim noise part
                self.b.append((self.trace[c]-self.a[c].sum())/(d-self.pi[c]))
                # Check for very small value of b
                if self.b[c]<EPS: 
                    self.b[c]=EPS
                # Compute logdet
                self.logdet.append(sp.log(self.a[c]).sum() + (d-self.pi[c])*sp.log(self.b[c])) 
                # Update the Q matrices
                self.Q[c] = self.Q[c][:,:self.pi[c]]
                
        elif self.model in ('M3','M4','M7','M8'):# Noise common
            # Estimation of b
            denom = d - sum(map(lambda prop,pi:prop*pi,self.prop,self.pi))
            num = sum(map(lambda prop,pi,L,trace:prop*(trace-L[:pi].sum()),self.prop,self.pi,self.L,self.trace))

            # Check for very small values of b
            if num<EPS:
                self.b = [EPS for i in xrange(C)] 
            elif denom<EPS:
                self.b = [1/EPS for i in xrange(C)] 
            else:
                self.b = [num/denom for i in xrange(C)]               
            
            for c in xrange(C):
                # Estim signal part
                self.a.append(self.L[c][:self.pi[c]])
                if self.model in ('M7','M8'):
                    self.a[c][:] = self.a[c][:].mean()
                # Compute logdet
                self.logdet.append(sp.log(self.a[c]).sum() + (d-self.pi[c])*sp.log(self.b[c])) 
                # Update the Q matrices
                self.Q[c] = self.Q[c][:,:self.pi[c]]
                
        # Compute the number of parameters of the model
        self.q = C*d + (C-1) + sum(map(lambda p:p*(d-(p+1)/2),self.pi)) # Mean vectors + proportion + eigenvectors
        if self.model in ('M1','M3','M5','M7'): # Number of noise subspaces
            self.q += C 
        elif self.model in ('M2','M4','M6','M8'):
            self.q += 1 
        if self.model in ('M1','M2'): # Size of signal subspaces
            self.q += sum(self.pi)+C 
        elif self.model in ('M3','M4'):
            self.q += sum(self.pi)+ 1
        elif self.model in ('M5','M6'):
            self.q += 2*C
        elif self.model in ('M7','M8'):
            self.q += C+1               
        
    def CV(self,x,y,param,v=5,seed=0):
        """
        This function computes the cross validation estimate of the Kappa coefficient of agreement given a set of parameters in the supervised case. 
        To speed up the processing, the empirical estimate (mean, proportion, eigendecomposition) is done only one for each fold.
        
        :param x: The sample matrix, is of size x \times d where n is the number of samples and d is the number of variables
        :param y: The vector of corresponding labels, is of size n \times 1 in the supervised case, otherwise it is None
        :param param: A dictionnary of parameters.
        :param v: the number of folds of the CV.
        :param seed: the initial state of the random generator.
        :return: the optimal value for the given model and the corresponding Kappa
        """
        # Initialization of the stratified K-Fold
        KF = StratifiedKFold(y.reshape(y.size,),v,random_state=seed)

        # Get parameters grid
        if self.model in ('M1','M3','M5','M7'): # TODO: Add other models
            param_grid = param['th']
        elif self.model in ('M2','M4','M6','M8'):
            param_grid = param['p']
            
        # Initialize the confusion matrix and the Kappa coefficient vector
        acc,Kappa = ai.CONFUSION_MATRIX(),sp.zeros((len(param_grid)))
        for train,test in KF:
            modelTemp = HDGMM(model=self.model)
            modelTemp.fit_init(x[train,:],y[train])
            for i,param_grid_ in enumerate(param_grid):
                # Fit model on train subests
                if modelTemp.model in ('M1','M3','M5','M7'):
                    param_= {'th':param_grid_}
                elif modelTemp.model in ('M2','M4','M6','M8'):
                    param_= {'p':param_grid_}
                modelTemp.fit_update(param_)
                # Predict on test subset
                yp = modelTemp.predict(x[test,:])
                acc.compute_confusion_matrix(yp,y[test])
                Kappa[i] += acc.Kappa
                modelTemp.free()
        Kappa /= v
        # Select the value with the highest Kappa value
        ind = sp.argmax(Kappa)
        return param_grid[ind],Kappa[ind]

    def loglike(self,x):
        """
        Compute the log likelyhood given a set of samples.
        :param x: The sample matrix, is of size x \times d where n is the number of samples and d is the number of variables
        """
        ## Get some parameters
        n = x.shape[0]

        ## Compute the membership function
        K = self.predict(x,out='ki')

        ## Compute the Loglikelhood
        K *= (-0.5)
        Km = K.max(axis=1).reshape(n,1)
        LL = (sp.log(sp.exp(K-Km).sum(axis=1))+Km).sum()
        K *= -2
        return LL,K
