# -*- coding: utf-8 -*-
"""[3] 지수 산출 엔트리."""
from . import indexer


def run(backtest: bool = False):
    res = indexer.run()
    if backtest:
        from . import backtest as bt
        bt.run()
    return res


if __name__ == "__main__":
    run()
