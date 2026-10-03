"""Synchronous handler-level assertions through the production step registry.

These replace direct calls to the legacy private _derive method. Runtime and
cancellation behavior are exercised separately through FunctionStep/PipeRuntime.
"""
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionContext


def execute_registered(factory, node, inputs):
    step = factory.build(node=node, dependencies=tuple(inputs), bindings={})
    return step._handler(ExecutionContext(), inputs)
