import numpy as np

def smoothing_derivative(head, time, method="bourdet"):
    """Calculate the derivative of the drawdown curve.

    Parameters
    ----------
    head : :class: 'array'
        An array with the observed head values.
    time: :class: 'array'
        An array with the time values for the observed head values.
    method : :class:`str`, optional
        Method to calculate the time derivative.
        Default: "bourdet"

    Returns
    -------
    The derivative of the observed heads.

    """
    # create arrays for the input of head and time.
    derhead = np.zeros(len(head))
    t = np.arange(len(time))
    if method == "bourdet":
        for i in t[1:-1]:
            # derivative approximation by Bourdet (1989)
            dh = (
                (
                    (head[i] - head[i - 1])
                    / (np.log(time[i]) - np.log(time[i - 1]))
                    * (np.log(time[i + 1]) - np.log(time[i]))
                )
                + (
                    (head[i + 1] - head[i])
                    / (np.log(time[i + 1]) - np.log(time[i]))
                    * (np.log(time[i]) - np.log(time[i - 1]))
                )
            ) / (
                (np.log(time[i]) - np.log(time[i - 1]))
                + (np.log(time[i + 1]) - np.log(time[i]))
            )
            derhead[i] = dh
        return derhead
    else:
        raise ValueError(
            f"smoothing_derivative: method '{method}' is unknown!"
        )
