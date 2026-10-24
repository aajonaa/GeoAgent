# Unmodified original kernels; full original source and license retained in originals/pyglue.
import multiprocessing

class InputError(Exception):
    """Exception raised for errors in the input."""
    pass

class GLUEEvaluatorKernel(multiprocessing.Process):
    def __init__(self, model=None, GLUEparams=None, stdparams=None,
                 rules=None, ruleargs=None, mp=False,
                 input_queue=None, result_queue=None):
        if mp:
            multiprocessing.Process.__init__(self)
        self.model = model
        if isinstance(GLUEparams, list):
            self.GLUEparams = GLUEparams
        else:
            raise TypeError('GLUEparams should be passed as a list')
        if isinstance(stdparams, dict):
            self.stdparams = stdparams
        else:
            self.stdparams = {}
        if len(rules) != len(ruleargs):
            raise InputError('Rules and Rule arguments do not match')
        self.rulesandargs = zip(rules, ruleargs)
        self.input_queue = input_queue
        self.result_queue = result_queue

    def evaluate(self, result):
        '''Evaluate result set by rules'''
        evalresult = []
        for func, args in self.rulesandargs:
            argsloc = args.copy()
            for k, v in argsloc.iteritems():
                if v in result:
                    argsloc[k] = result[v]
            evalresult.append(func(**argsloc))
        return False not in evalresult

    def run_and_evaluate(self, rid):
        ''' Runs model and evaluates result,
            returns [rid, prms, self.GLUEeval.evaluate(result)]
            '''
        try:
            print(rid)
            prms = dict([[prm.name, prm.get_value()] for prm in self.GLUEparams])
            result = self.model(**dict(prms, **self.stdparams))
            return [rid, prms, self.evaluate(result)]
        except:
            return [rid, prms, False]
