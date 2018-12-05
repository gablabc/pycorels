from libc.string cimport strdup, strcpy
from libc.stdlib cimport malloc, free
import numpy as np
cimport numpy as np
cimport cython

cdef extern from "src/corels/rule.h":
    ctypedef unsigned long* VECTOR
    cdef struct rule:
        VECTOR truthtable
        char* features
        int cardinality
        int* ids
        int support

    ctypedef rule rule_t
    
    int ascii_to_vector(char *, size_t, int *, int *, VECTOR *)
    void rules_free(rule_t *, const int, int);
    int rule_vfree(VECTOR *)
    int rule_vinit(int, VECTOR *)
    void rule_not(VECTOR, VECTOR, int, int *)
    int rule_isset(VECTOR, int)

cdef extern from "src/corels/run.h":
    int run_corels_begin(double c, char* vstring, int curiosity_policy,
                      int map_type, int freq, int ablation, int calculate_size, int nrules, int nlabels,
                      int nsamples, rule_t* rules, rule_t* labels, rule_t* meta)

    int run_corels_loop(size_t max_num_nodes)

    double run_corels_end(int** rulelist, int* rulelist_size, int** classes)

cdef extern from "src/utils.h":
    int mine_rules(char **features, rule_t *samples, int nfeatures, int nsamples, 
                int max_card, double min_support, rule_t **rules_out, int verbose)

    int minority(rule_t* rules, int nrules, rule_t* labels, int nsamples, rule_t* minority_out, int verbose)

@cython.boundscheck(False)
@cython.wraparound(False)
def predict_wrap(np.ndarray[np.uint8_t, ndim=2] X, features, rules):
    cdef int nsamples = X.shape[0]
    cdef int nfeatures = X.shape[1]
    
    if nfeatures != len(features) - 1:
        raise ValueError("Feature count mismatch between prediction data (" + str(nfeatures) +
                         ") and rulelist (" + str(len(features) - 1) + ")")

    cdef np.ndarray out = np.zeros(nsamples, dtype=np.uint8)
    cdef int nrules = len(rules) - 1
    if nrules < 0:
        return out

    cdef int s, r, next_rule, nidx, a, idx, c
    cdef int default = rules[nrules]['prediction']

    cdef int* antecedent_lengths = <int*>malloc(sizeof(int) * nrules)
    cdef int* predictions = <int*>malloc(sizeof(int) * nrules)
    cdef int** antecedents = <int**>malloc(sizeof(int*) * nrules)
    
    for r in range(nrules):
        antecedent_lengths[r] = len(rules[r]['antecedents'])
        predictions[r] = rules[r]['prediction']
        antecedents[r] = <int*>malloc(sizeof(int) * antecedent_lengths[r])
        for a in range(antecedent_lengths[r]):
            antecedents[r][a] = rules[r]['antecedents'][a]

    for s in range(nsamples):
        for r in range(nrules):
            next_rule = 0
            nidx = antecedent_lengths[r]
            for a in range(nidx):
                idx = antecedents[r][a]
                c = 1
                if idx < 0:
                    idx = -idx
                    c = 0

                idx = idx - 1
                if idx >= nfeatures or X[s, idx] != c:
                    next_rule = 1
                    break

            if next_rule == 0:
                out[s] = predictions[r];
                break

        if next_rule == 1:
            out[s] = default

    for r in range(nrules):
        free(antecedents[r])
    free(antecedents)
    free(predictions)
    free(antecedent_lengths)

    return out

cdef rule_t* _to_vector(np.ndarray[np.uint8_t, ndim=2] X, int* ncount):
    d0 = X.shape[0]
    d1 = X.shape[1]
    cdef rule_t* vectors = <rule_t*>malloc(d0 * sizeof(rule_t))
    if not vectors:
        raise MemoryError()

    cdef int nones;

    for i in range(d0):
        arrstr = ""
        for j in range(d1):
            arrstr += str(X[i][j])
        
        bytestr = arrstr.encode('ascii')
        if ascii_to_vector(bytestr, len(arrstr), ncount, &nones, &vectors[i].truthtable) != 0:
            for j in range(i):
                rule_vfree(&vectors[j].truthtable)

            free(vectors)
            raise ValueError("Could not load samples")

        vectors[i].ids = NULL
        vectors[i].features = NULL
        vectors[i].cardinality = 1
        vectors[i].support = nones

    return vectors

cdef _free_vector(rule_t* vs, int count):
    if not vs:
        return
    
    for i in range(count):
        rule_vfree(&vs[i].truthtable)
        if vs[i].ids:
            free(vs[i].ids)

        if vs[i].features:
            free(vs[i].features)
    
    free(vs)

"""
cdef _to_nparray(rule_t* X, int nrules, int nsamples):
    arr = np.empty([ nrules, nsamples ], dtype=np.uint8)

    for i in range(nrules):
        for j in range(nsamples):
            arr[i][j] = rule_isset(X[i].truthtable, j)

    return arr
"""
cdef rule_t* rules = NULL
cdef rule_t* labels_vecs = NULL
cdef rule_t* minor = NULL
cdef int nrules = 0

def fit_wrap_begin(np.ndarray[np.uint8_t, ndim=2] samples, 
             np.ndarray[np.uint8_t, ndim=2] labels,
             features, int max_card, double min_support, verbosity_str, int mverbose,
             double c, int policy, int map_type, int log_freq, int ablation,
             int calculate_size):
    global rules
    global labels_vecs
    global minor
    global nrules

    cdef int nfeatures = 0
    cdef rule_t* samples_vecs = _to_vector(samples, &nfeatures)

    nsamples = samples.shape[0]

    if nfeatures > len(features):
        _free_vector(samples_vecs, nsamples)
        raise ValueError("Feature count mismatch between sample data (" + str(nfeatures) + 
                         ") and feature names (" + str(len(features)) + ")")

    cdef char** features_vec = <char**>malloc(nfeatures * sizeof(char*))
    if not features_vec:
        _free_vector(samples_vecs, nsamples)
        raise MemoryError()

    for i in range(nfeatures):
        bytestr = features[i].encode('ascii')
        features_vec[i] = strdup(bytestr)

    if rules != NULL and nrules != 0:
        _free_vector(rules, nrules)
        rules = NULL
        nrules = 0

    cdef int r = mine_rules(features_vec, samples_vecs, nfeatures, nsamples,
                max_card, min_support, &rules, mverbose)

    for i in range(nfeatures):
        free(features_vec[i])
    free(features_vec)
    
    _free_vector(samples_vecs, nsamples)

    if r == -1 or rules == NULL:
        raise MemoryError();
    
    nrules = r

    verbosity_ascii = verbosity_str.encode('ascii')
    cdef char* verbosity = verbosity_ascii

    if labels_vecs != NULL:
        _free_vector(labels_vecs, 2)
        labels_vecs = NULL

    cdef int nsamples_chk = 0
    try:
        labels_vecs = _to_vector(labels, &nsamples_chk)
    except:
        _free_vector(rules, nrules)
        raise

    if nsamples_chk != nsamples:
        _free_vector(labels_vecs, 2)
        _free_vector(rules, nrules)
        raise ValueError("Sample count mismatch between label (" + str(nsamples_chk) +
                         ") and rule data (" + str(nsamples) + ")")

    labels_vecs[0].features = <char*>malloc(8)
    labels_vecs[1].features = <char*>malloc(8)
    strcpy(labels_vecs[0].features, "label=0")
    strcpy(labels_vecs[1].features, "label=1")
    
    if minor != NULL:
        _free_vector(minor, 1)
        minor = NULL

    minor = <rule_t*>malloc(sizeof(rule_t))

    cdef int mr = minority(rules, nrules, labels_vecs, nsamples, minor, mverbose)
    if mr != 0:
        _free_vector(labels_vecs, 2)
        _free_vector(rules, nrules)
        raise MemoryError();
    
    cdef int rb = run_corels_begin(c, verbosity, policy, map_type, log_freq, ablation, calculate_size,
                   nrules, 2, nsamples, rules, labels_vecs, minor)
    if rb == -1:
        _free_vector(labels_vecs, 2)
        labels_vecs = NULL
        _free_vector(minor, 1)
        minor = NULL
        _free_vector(rules, nrules)
        rules = NULL
        nrules = 0

        return False

    return True

def fit_wrap_loop(size_t max_nodes):
    cdef size_t max_num_nodes = max_nodes
    return (run_corels_loop(max_num_nodes) != -1)

def fit_wrap_end():
    global rules
    global labels_vecs
    global minor
    global nrules

    cdef int rulelist_size = 0
    cdef int* rulelist = NULL
    cdef int* classes = NULL
    cdef double acc = run_corels_end(&rulelist, &rulelist_size, &classes)

    r_out = []
    if classes != NULL:
        for i in range(rulelist_size):
            r_out.append({})
            r_out[i]['antecedents'] = []
            for j in range(rules[rulelist[i]].cardinality):
                r_out[i]['antecedents'].append(rules[rulelist[i]].ids[j])

            r_out[i]['prediction'] = classes[i]

        r_out.append({ 'antecedents': [0], 'prediction': classes[rulelist_size] })
        if rulelist != NULL:
            free(rulelist)
        free(classes)
    
    _free_vector(labels_vecs, 2)
    labels_vecs = NULL
    _free_vector(minor, 1)
    minor = NULL
    _free_vector(rules, nrules)
    rules = NULL
    nrules = 0

    return acc, r_out