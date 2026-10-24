# Copyright (c) 2020 Clebson Carvalho de Farias. See licenses/HidroComp_LICENSE.
# Exact class excerpts; only import wiring is local.
import pandas as pd
from abc import ABCMeta, abstractmethod

class QuantifyUncertainty(object, metaclass=ABCMeta):

    def __init__(self, reference, compared):
        """Dados de entrada:
            reference: <pd.DataFrame> com as magnitudes estimadas pela distribuiçao
            de referência.
            compared: <dict> contendo os <pd.DataFrame> com as magnitudes estimadas
            pelas distribuições a serem comparadas.
        """
        self.reference = reference
        self.compared = compared

    @abstractmethod
    def calculo_erro(self):
        pass

    def quantify(self):
        df_comp = pd.DataFrame()
        serie_comp = self.calculo_erro()

        df_comp = serie_comp.to_frame()

        return df_comp
class RMSE(QuantifyUncertainty):
    """
    Root Mean Square Error - RMSE
    RMSE = [1/n * soma(xi - Qmax)²]^1/2
    """
    def __init__(self, reference, compared):
        super().__init__(reference, compared)

    def calculo_erro(self):
        prob = list()
        rmse = list()
        for i in self.reference.index:
            sum = 0
            prob.append(i)
            for j in self.compared[i].values:
                aux = (j - self.reference[i]) ** 2
                sum += aux

            rmse_value = (1/len(self.compared)*sum) ** 0.5
            rmse.append(rmse_value)

        rmse_serie = pd.Series(rmse, index=prob, name='RMSE')
        return rmse_serie
