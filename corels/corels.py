from __future__ import print_function, division, with_statement
from . import _corels
from .utils import check_consistent_length, check_array, check_is_fitted, get_feature, check_in, check_features, check_rulelist, RuleList
import numpy as np
import pickle

class CorelsClassifier:
    """Certifiably Optimal RulE ListS classifier.

    This class implements the CORELS algorithm, designed to produce human-interpretable, optimal
    rulelists for binary feature data and binary classification. As an alternative to other
    tree based algorithms such as CART, CORELS provides a certificate of optimality for its 
    rulelist given a training set, leveraging multiple algorithmic bounds to do so.

    In order to use run the algorithm, create an instance of the `CorelsClassifier` class, 
    providing any necessary parameters in its constructor, and then call `fit` to generate
    a rulelist. `printrl` prints the generated rulelist, while `predict` provides
    classification predictions for a separate test dataset with the same features. To determine 
    the algorithm's accuracy, run `score` on an evaluation dataset with labels.
    To save a generated rulelist to a file, call `save`. To load it back from the file, call `load`.

    Attributes
    ----------
    c : float, optional (default=0.01)
        Regularization parameter. Higher values penalize longer rulelists.

    n_iter : int, optional (default=1000)
        Maximum number of nodes (rulelists) to search before exiting.

    map_type : str, optional (default="prefix")
        The type of prefix map to use. Supported maps are "none" for no map,
        "prefix" for a map that uses rule prefixes for keys, "captured" for
        a map with a prefix's captured vector as keys.

    policy : str, optional (default="lower_bound")
        The search policy for traversing the tree (i.e. the criterion with which
        to order nodes in the queue). Supported criteria are "bfs", for breadth-first
        search; "curious", which attempts to find the most promising node; 
        "lower_bound" which is the objective function evaluated with that rulelist
        minus the default prediction error; "objective" for the objective function
        evaluated at that rulelist; and "dfs" for depth-first search.

    verbosity : list, optional (default=["progress"])
        The verbosity levels required. A list of strings, it can contain any
        subset of ["rule", "label", "samples", "progress", "log", "loud"].
        - "rule" prints the a summary for each rule generated.
        - "label" prints a summary of the class labels.
        - "samples" produces a complete dump of the rules and/or label 
            data. "rule" being or "label" must also be already provided.
        - "progress" prints periodic messages as corels runs.
        - "log" prints machine information.
        - "loud" is the equivalent of ["progress", "log", "label", "rule"]

    ablation : int, optional (default=0)
        Specifies addition parameters for the bounds used while searching. Accepted
        values are 0 (all bounds), 1 (no antecedent support bound), and 2 (no
        lookahead bound).

    max_card : int, optional (default=2)
        Maximum cardinality allowed when mining rules. Can be any value greater than
        or equal to 1. For instance, a value of 2 would only allow rules that combine
        at most two features in their antecedents.

    min_support : float, optional (default=0.01)
        The fraction of samples that a rule must capture in order to be used. 1 minus
        this value is also the maximum fraction of samples a rule can capture.
        Can be any value between 0.0 and 1.0.

    References
    ----------
    Elaine Angelino, Nicholas Larus-Stone, Daniel Alabi, Margo Seltzer, and Cynthia Rudin.
    Learning Certifiably Optimal Rule Lists for Categorical Data. KDD 2017.
    Journal of Machine Learning Research, 2018; 19: 1-77. arXiv:1704.01701, 2017

    Examples
    --------
    >>> import numpy as np
    >>> from corels import CorelsClassifier
    >>> X = np.array([ [1, 0, 1], [0, 1, 0], [1, 1, 1] ])
    >>> y = np.array([ 1, 0, 1])
    >>> c = CorelsClassifier(verbosity=[])
    >>> c.fit(X, y)
    ...
    >>> print(c.predict(X))
    [ True False  True ]
    """
    
    def __init__(self, c=0.01, n_iter=10000, map_type="prefix", policy="lower_bound",
                 verbosity=["progress"], ablation=0, max_card=2, min_support=0.01):
        self.c = c
        self.n_iter = n_iter
        self.map_type = map_type
        self.policy = policy
        self.verbosity = verbosity
        self.ablation = ablation
        self.max_card = max_card
        self.min_support = min_support

    def fit(self, X, y, features=[], prediction_name="prediction"):
        """
        Build a CORELS classifier from the training set (X, y).

        Parameters
        ----------
        X : array-like, shape = [n_samples, n_features]
            The training input samples. All features must be binary, and the matrix
            is internally converted to dtype=np.uint8.

        y : array-line, shape = [n_samples]
            The target values for the training input. Must be binary.
        
        features : list, optional(default=[])
            A list of strings of length n_features. Specifies the names of each
            of the features. If an empty list is provided, the feature names
            are set to the default of ["feature1", "feature2"... ].

        prediction_name : string, optional(default="prediction")
            The name of the feature that is being predicted.

        Returns
        -------
        self : obj
        """

        if not isinstance(self.c, float) or self.c < 0.0 or self.c > 1.0:
            raise ValueError("Regularization constant (c) must be a float between"
                             " 0.0 and 1.0, got: " + str(self.c))
        if not isinstance(self.n_iter, int) or self.n_iter < 0:
            raise ValueError("Max nodes must be a positive integer, got: " + str(self.n_iter))
        if not isinstance(self.ablation, int) or self.ablation > 2 or self.ablation < 0:
            raise ValueError("Ablation must be an integer between 0 and 2"
                             ", inclusive, got: " + str(self.ablation))
        if not isinstance(self.map_type, str):
            raise ValueError("Map type must be a string, got: " + str(self.map_type))
        if not isinstance(self.policy, str):
            raise ValueError("Policy must be a string, got: " + str(self.policy))
        if not isinstance(self.verbosity, list):
            raise ValueError("Verbosity must be a list of strings, got: " + str(self.verbosity))
        if not isinstance(self.min_support, float) or self.min_support < 0.0 or self.min_support > 1.0:
            raise ValueError("Minimum support must be a float between"
                             " 0.0 and 1.0, got: " + str(self.min_support))
        if not isinstance(self.max_card, int) or self.max_card < 1:
            raise ValueError("Max cardinality must be an integer greater than or equal to 1"
                             ", got: " + str(self.max_card))
        
        if not isinstance(prediction_name, str):
            raise ValueError("Prediction name must be a string, got: " + str(prediction_name))
       
        check_consistent_length(X, y)
        label = check_array(y, ndim=1, dtype=np.bool, order='C')
        labels = np.array([ np.invert(label), label ], dtype=np.uint8)
        
        samples = np.array(check_array(X, ndim=2, dtype=np.bool, order='C'), dtype=np.uint8)

        n_samples = samples.shape[0]
        n_features = samples.shape[1]
        n_labels = labels.shape[0]
        
        rl = RuleList()
        
        if features:
            check_features(features)
            rl.features = list(features)
        else:
            rl.features_ = []
            for i in range(n_features):
                rl.features.append("feature" + str(i + 1))

        if rl.features and len(rl.features) != n_features:
            raise ValueError("Feature count mismatch between sample data (" + str(n_features) + 
                             ") and feature names (" + str(len(rl.features)) + ")")
        
        rl.prediction_name = prediction_name

        allowed_verbosities = ["rule", "label", "samples", "progress", "log", "loud"]
        for v in self.verbosity:
            if not isinstance(v, str):
                raise ValueError("Verbosity flags must be strings, got: " + str(v))

            check_in("Verbosities", allowed_verbosities, v)
        
        if "samples" in self.verbosity \
              and "rule" not in self.verbosity \
              and "label" not in self.verbosity:
            raise ValueError("'samples' verbosity option must be combined with at" + 
                             " least one of 'rule' or 'label'")

        # Verbosity for rule mining and minority bound. 0 is quiet, 1 is verbose
        m_verbose = 0
        if "loud" in self.verbosity or "mine" in self.verbosity:
            m_verbose = 1
        
        verbose = ",".join(self.verbosity)

        map_types = ["none", "prefix", "captured"]
        policies = ["bfs", "curious", "lower_bound", "objective", "dfs"]

        check_in("Map type", map_types, self.map_type)
        check_in("Search policy", policies, self.policy)

        map_id = map_types.index(self.map_type)
        policy_id = policies.index(self.policy)

        fr = _corels.fit_wrap_begin(samples, labels, rl.features,
                             self.max_card, self.min_support, verbose, m_verbose, self.c, policy_id,
                             map_id, self.ablation, False)
        
        acc = 0.0

        if fr:
            early = False
            try:
                while _corels.fit_wrap_loop(self.n_iter):
                    pass
            except KeyboardInterrupt:
                print("\nExiting early")
                early = True
             
            rl.rules = _corels.fit_wrap_end(early)
            
            self.rl_ = rl
            self.is_fitted_ = True
        else:
            print("Error running model! Exiting")

        return self

    def predict(self, X):
        """
        Predict classifications of the input samples X.

        Arguments
        ---------
        X : array-like, shape = [n_samples, n_features]
            The training input samples. All features must be binary, and the matrix
            is internally converted to dtype=np.uint8. The features must be the same
            as those of the data used to train the model.

        Returns
        -------
        p : array of shape = [n_samples].
            The classifications of the input samples.
        """

        check_is_fitted(self, "is_fitted_")
        check_rulelist(self.rl_)        

        samples = np.array(check_array(X, ndim=2, dtype=np.bool, order='C'), dtype=np.uint8)
        
        if samples.shape[1] != len(self.rl_.features):
            raise ValueError("Feature count mismatch between eval data (" + str(X.shape[1]) + 
                             ") and feature names (" + str(len(self.rl_.features)) + ")")

        return np.array(_corels.predict_wrap(samples, self.rl_.rules), dtype=np.bool)

    def score(self, X, y):
        """
        Score the algorithm on the input samples X with the labels y. Alternatively,
        score the predictions X against the labels y (where X has been generated by 
        `predict` or something similar).

        Arguments
        ---------
        X : array-like, shape = [n_samples, n_features] OR shape = [n_samples]
            The input samples, or the sample predictions. All features must be binary.
        
        y : array-like, shape = [n_samples]
            The input labels. All labels must be binary.

        Returns
        -------
        a : float
            The accuracy, from 0.0 to 1.0, of the rulelist predictions
        """

        check_consistent_length(X, y)
        labels = check_array(y, ndim=1, dtype=np.bool, order='C')
       
        p = check_array(X, dtype=np.bool, order='C')
        if X.ndim == 2:
            p = self.predict(X)
        elif X.ndim != 1:
            raise ValueError("Input samples must have only 1 or 2 dimensions, got " + str(X.ndim) +
                             " dimensions")

        a = np.sum(np.invert(np.logical_xor(p, labels))) / float(p.shape[0])

        return a
    
    def save(self, fname):
        """
        Save the rulelist to a file, using python's pickle module.

        Parameters
        ----------
        fname : string
            File name to store the rulelist in
        
        Returns
        -------
        self : obj
        """

        check_is_fitted(self, "is_fitted_")
        check_rulelist(self.rl_)

        with open(fname, "wb") as f:
            pickle.dump({ "f": self.rl_.features, "r": self.rl_.rules, "p": self.rl_.prediction_name }, f)

        return self

    def load(self, fname):
        """
        Load a rulelist from a file, using python's pickle module.
        
        Parameters
        ----------
        fname : string
            File name to load the rulelist from
        
        Returns
        -------
        self : obj
        """

        with open(fname, "rb") as f:
            rl_dict = pickle.load(f)
            if not "r" in rl_dict or not "f" in rl_dict or not "p" in rl_dict:
                raise ValueError("Invalid rulelist file")
            
            rl = RuleList()
            rl.rules = rl_dict["r"]
            rl.features = rl_dict["f"]
            rl.prediction_name = rl_dict["p"]
            check_rulelist(rl)

            self.rl_ = rl
            self.is_fitted_ = True

        return self

    def printrl(self):
        """
        Print the rulelist in a human-friendly format.

        Returns
        -------
        self : obj
        """

        print(self)
        return self
    
    def __str__(self):
        check_is_fitted(self, "is_fitted_")
        return self.rl_.__str__()
