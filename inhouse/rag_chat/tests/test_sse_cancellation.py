"""Real SSE/AnyIO ASGI disconnect + real AST retry, deterministic offline I/O."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import threading
from types import SimpleNamespace

import anyio
import pytest
from sse_starlette.sse import EventSourceResponse

from rag_chat.app.routers import chat
from rag_core.ragkit import live_multihop as live
from rag_core.ragkit.history_context import InMemoryHistoryStore
from rag_core.ragkit.chatbot_events import ChatEvent


async def observed(event):
    with anyio.fail_after(2):
        while not event.is_set():
            await anyio.sleep(0.005)


@pytest.fixture
def wiring(monkeypatch):
    closed = threading.Event()
    trace_active = ContextVar('test_trace_active', default=False)

    @contextmanager
    def trace(**kwargs):
        token = trace_active.set(True)
        try:
            yield None
        finally:
            trace_active.reset(token)
            closed.set()

    def session(request, profile, session_id):
        with chat._session_turn_lock(session_id):
            yield from chat._run_document_qa(request, session_id, profile)

    monkeypatch.setattr(chat.session_store, 'get_or_create_session', lambda *a: 'cancel-fixture')
    monkeypatch.setattr(chat, '_run_chat_session', session)
    monkeypatch.setattr(chat, 'chat_trace', trace)
    monkeypatch.setattr(chat, 'update_observation', lambda *a, **k: None)
    monkeypatch.setattr(chat, 'get_settings', lambda: SimpleNamespace(MSR_DB='unused'))
    monkeypatch.setattr(chat, 'get_chat_client', lambda: None)
    monkeypatch.setattr(live, '_AST_CACHE', {})
    monkeypatch.setattr(live, '_AST_CACHE_HITS', 0)
    monkeypatch.setattr(live, '_AST_CACHE_MISSES', 0)
    monkeypatch.setattr(live, '_HISTORY', InMemoryHistoryStore())
    return closed


@pytest.mark.parametrize('endpoint,late_valid', [('pubchat', False), ('prichat', False), ('chat', False),
                                               ('legacy_control', False), ('pubchat', True)])
def test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns(monkeypatch, wiring, endpoint, late_valid):
    started, release, exited, core_closed = (threading.Event() for _ in range(4))
    calls = []
    live_tasks = []
    downstream = []

    def forbidden_downstream(*args):
        downstream.append(True)
        raise AssertionError('cancelled run_live must never reach lowering/retrieval')

    monkeypatch.setattr(live, '_resolve_history_references', forbidden_downstream)

    class LLM:
        def invoke(self, **kwargs):
            calls.append(kwargs['task'])
            started.set()
            try:
                assert release.wait(3), 'test failed to release blocking I/O'
                if late_valid:
                    return SimpleNamespace(output=live.ASTProgramModel.model_validate({
                        'nodes': [
                            {'node_id': 'mineral', 'operator': 'entity', 'args': {'values': ['니켈']}},
                            {'node_id': 'prices', 'operator': 'retrieve', 'inputs': [{'node_id': 'mineral'}],
                             'args': {'domain': 'price', 'metric': 'price'}},
                        ], 'roots': ['prices']}))
                return SimpleNamespace(output=SimpleNamespace(request_class='DATA_REQUEST', nodes=[], roots=[]))
            finally:
                exited.set()

    async def events(**kwargs):
        try:
            yield ChatEvent('status', {'stage': 1})
            yield ChatEvent('status', {'stage': 2})
            task = asyncio.create_task(live.run_live_multihop(
                llm=LLM(), message='cancellation fixture', session_id='cancel-fixture',
                profile=kwargs['profile'], history=[]))
            live_tasks.append(task)
            await task
        finally:
            core_closed.set()

    monkeypatch.setattr(chat, 'chat_turn', events)

    async def scenario():
        request = chat.ChatRequest(user_id='offline', message='cancellation fixture', mode='document')
        response = (EventSourceResponse(chat._run_chat(request, 'public')) if endpoint == 'legacy_control'
                    else getattr(chat, endpoint)(request))
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            await observed(started)
            if endpoint == 'legacy_control':
                # Same old SSE threadpool path: cancellation is shielded until
                # next() returns. Release I/O later to avoid hanging the test.
                asyncio.get_running_loop().call_later(0.05, release.set)
            return {'type': 'http.disconnect'}

        try:
            with anyio.fail_after(2):
                await response({'type': 'http'}, receive, send)
            await observed(core_closed)
            await observed(wiring)
            assert 'cancel-fixture' not in chat._session_locks
            if endpoint == 'legacy_control':
                assert len(calls) == 3  # Actual retry bug reproduced.
            else:
                assert len(calls) == 1
                assert len(live_tasks) == 1 and live_tasks[0].cancelled()
                assert not exited.is_set()  # In-flight sync I/O not claimed killed.
                assert not any(b'event: done' in x.get('body', b'') or b'event: error' in x.get('body', b'') for x in sent)
        finally:
            release.set()
        await observed(exited)
        await anyio.sleep(0.02)
        assert len(calls) == (3 if endpoint == 'legacy_control' else 1)
        assert not downstream
        assert not (await live._HISTORY.get_context('cancel-fixture')).turns

    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [False, True])
def test_normal_completion_and_error_keep_one_done(monkeypatch, wiring, failure):
    core_closed = threading.Event()

    async def events(**kwargs):
        try:
            yield ChatEvent('status', {'stage': 1})
            if failure:
                raise ValueError('synthetic failure')
            yield ChatEvent('delta', {'delta': 'hello'})
            yield ChatEvent('done', {'done': True})
            raise AssertionError('must not advance after done')
        finally:
            core_closed.set()

    monkeypatch.setattr(chat, 'chat_turn', events)

    async def scenario():
        response = chat.pubchat(chat.ChatRequest(user_id='offline', message='fixture'))
        sent = []
        async def send(message):
            sent.append(message)
        async def receive():
            await anyio.sleep_forever()
        with anyio.fail_after(2):
            await response({'type': 'http'}, receive, send)
        body = b''.join(x.get('body', b'') for x in sent)
        assert body.count(b'event: done') == 1
        assert body.count(b'event: error') == int(failure)
        await observed(core_closed)
        await observed(wiring)
        assert 'cancel-fixture' not in chat._session_locks
    asyncio.run(scenario())


def test_disconnect_while_send_is_blocked_closes_suspended_generator(monkeypatch, wiring):
    core_closed = threading.Event()
    async def events(**kwargs):
        try:
            yield ChatEvent('status', {'stage': 1})
            raise AssertionError('no further work after disconnect')
        finally:
            core_closed.set()
    monkeypatch.setattr(chat, 'chat_turn', events)
    async def scenario():
        sending = anyio.Event()
        async def send(message):
            if message['type'] == 'http.response.body':
                sending.set()
                await anyio.sleep_forever()
        async def receive():
            await sending.wait()
            return {'type': 'http.disconnect'}
        response = chat.pubchat(chat.ChatRequest(user_id='offline', message='fixture'))
        with anyio.fail_after(2):
            await response({'type': 'http'}, receive, send)
        await observed(core_closed)
        await observed(wiring)
        assert 'cancel-fixture' not in chat._session_locks
    asyncio.run(scenario())


def test_cancelled_session_lock_waiter_does_not_run_or_release_owner(monkeypatch, wiring):
    entered = []
    async def events(**kwargs):
        entered.append(True)
        yield ChatEvent('done', {'done': True})
    monkeypatch.setattr(chat, 'chat_turn', events)
    async def scenario():
        response = chat.pubchat(chat.ChatRequest(user_id='offline', message='fixture'))
        async def send(message):
            pass
        async def receive():
            with anyio.fail_after(2):
                while chat._session_lock_counts.get('cancel-fixture') != 2:
                    await anyio.sleep(0.005)
            return {'type': 'http.disconnect'}
        with chat._session_turn_lock('cancel-fixture'):
            with anyio.fail_after(2):
                await response({'type': 'http'}, receive, send)
            await observed(wiring)
            assert not entered
            assert chat._session_lock_counts['cancel-fixture'] == 1
            assert chat._session_locks['cancel-fixture'].locked()
        assert 'cancel-fixture' not in chat._session_locks
    asyncio.run(scenario())


def test_send_failure_closes_trace_and_core(monkeypatch, wiring):
    core_closed = threading.Event()
    async def events(**kwargs):
        try:
            yield ChatEvent('status', {'stage': 1})
        finally:
            core_closed.set()
    monkeypatch.setattr(chat, 'chat_turn', events)
    async def scenario():
        async def send(message):
            if message['type'] == 'http.response.body':
                raise OSError('synthetic socket closure')
        async def receive():
            await anyio.sleep_forever()
        with pytest.raises(Exception):
            with anyio.fail_after(2):
                await chat.pubchat(chat.ChatRequest(user_id='offline', message='fixture'))({'type': 'http'}, receive, send)
        await observed(core_closed)
        await observed(wiring)
        assert 'cancel-fixture' not in chat._session_locks
    asyncio.run(scenario())
